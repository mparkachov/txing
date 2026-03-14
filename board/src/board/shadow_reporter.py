from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import os
import signal
import socket
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import paho.mqtt.client as mqtt

from .shadow_store import DEFAULT_SHADOW_FILE, save_shadow

LOGGER = logging.getLogger("board.shadow_reporter")
MQTT_LOGGER = logging.getLogger("board.shadow_reporter.mqtt")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CERT_DIR = REPO_ROOT / "certs"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_THING_NAME = "txing"
DEFAULT_IOT_ENDPOINT_FILE = DEFAULT_CERT_DIR / "iot-data-ats.endpoint"
DEFAULT_CERT_FILE = DEFAULT_CERT_DIR / "txing.cert.pem"
DEFAULT_KEY_FILE = DEFAULT_CERT_DIR / "txing.private.key"
DEFAULT_CA_FILE = DEFAULT_CERT_DIR / "AmazonRootCA1.pem"
DEFAULT_SCHEMA_FILE = DEFAULT_DOCS_DIR / "txing-shadow.schema.json"
DEFAULT_AWS_CONNECT_TIMEOUT = 20.0
DEFAULT_MQTT_PUBLISH_TIMEOUT = 10.0
DEFAULT_HEARTBEAT_SECONDS = 60.0
DEFAULT_RECONNECT_DELAY = 5.0


@dataclass(frozen=True)
class ReporterConfig:
    thing_name: str
    iot_endpoint: str
    cert_file: Path
    key_file: Path
    ca_file: Path
    schema_file: Path
    shadow_file: Path
    client_id: str
    board_name: str
    heartbeat_seconds: float
    aws_connect_timeout: float
    publish_timeout: float
    reconnect_delay: float
    once: bool


class AwsShadowClient:
    def __init__(self, config: ReporterConfig) -> None:
        self._config = config
        self._topic_update = f"$aws/things/{config.thing_name}/shadow/update"
        self._topic_update_accepted = (
            f"$aws/things/{config.thing_name}/shadow/update/accepted"
        )
        self._topic_update_rejected = (
            f"$aws/things/{config.thing_name}/shadow/update/rejected"
        )
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=config.client_id,
            protocol=mqtt.MQTTv311,
        )
        self._client.enable_logger(MQTT_LOGGER)
        self._client.tls_set(
            ca_certs=str(config.ca_file),
            certfile=str(config.cert_file),
            keyfile=str(config.key_file),
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe

        self._lock = threading.Lock()
        self._connection_done = threading.Event()
        self._response_done = threading.Event()
        self._connection_ready = False
        self._connection_error: RuntimeError | None = None
        self._pending_token: str | None = None
        self._pending_error: RuntimeError | None = None
        self._pending_response: dict[str, Any] | None = None
        self._loop_started = False
        self._ever_connected = False
        self._disconnect_requested = False

    def ensure_connected(self, *, timeout_seconds: float) -> None:
        with self._lock:
            if self._connection_ready:
                return
            self._connection_ready = False
            self._connection_error = None
            self._connection_done.clear()

        if not self._loop_started:
            self._client.loop_start()
            self._loop_started = True

        try:
            if self._ever_connected:
                rc = self._client.reconnect()
            else:
                rc = self._client.connect(self._config.iot_endpoint, port=8883, keepalive=60)
                self._ever_connected = True
        except Exception as err:
            raise RuntimeError(
                f"failed to connect to AWS IoT endpoint {self._config.iot_endpoint!r}: {err}"
            ) from err

        if rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"failed to initiate AWS IoT MQTT connection (rc={rc})"
            )

        if not self._connection_done.wait(timeout_seconds):
            raise RuntimeError(
                f"timed out waiting for AWS IoT MQTT readiness after {timeout_seconds:.1f}s"
            )

        with self._lock:
            if self._connection_error is not None:
                raise self._connection_error
            if not self._connection_ready:
                raise RuntimeError("AWS IoT MQTT did not become ready")

    def is_connected(self) -> bool:
        with self._lock:
            return self._connection_ready

    def publish_update(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        token = f"{self._config.client_id}-{os.getpid()}-{int(datetime.now(UTC).timestamp() * 1000)}"
        envelope = dict(payload)
        envelope["clientToken"] = token

        with self._lock:
            self._pending_token = token
            self._pending_error = None
            self._pending_response = None
            self._response_done.clear()

        encoded_payload = json.dumps(envelope, sort_keys=True)
        info = self._client.publish(self._topic_update, payload=encoded_payload, qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            with self._lock:
                self._pending_token = None
            raise RuntimeError(
                f"failed to publish shadow update to {self._topic_update} (rc={info.rc})"
            )

        if not self._response_done.wait(timeout_seconds):
            with self._lock:
                self._pending_token = None
            raise RuntimeError(
                f"timed out waiting for shadow update response after {timeout_seconds:.1f}s"
            )

        with self._lock:
            error = self._pending_error
            response = self._pending_response
            self._pending_token = None
            self._pending_error = None
            self._pending_response = None

        if error is not None:
            raise error
        if response is None:
            raise RuntimeError("AWS IoT shadow update returned no response payload")
        return response

    def close(self) -> None:
        self._disconnect_requested = True
        try:
            if self._loop_started and self.is_connected():
                self._client.disconnect()
        finally:
            if self._loop_started:
                self._client.loop_stop()

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        if int(reason_code) != 0:
            error = RuntimeError(
                f"AWS IoT MQTT CONNACK rejected (reason={reason_code})"
            )
            with self._lock:
                self._connection_ready = False
                self._connection_error = error
            self._connection_done.set()
            return

        LOGGER.info(
            "Connected to AWS IoT endpoint=%s thing=%s client_id=%s",
            self._config.iot_endpoint,
            self._config.thing_name,
            self._config.client_id,
        )
        result, _mid = client.subscribe(
            [
                (self._topic_update_accepted, 1),
                (self._topic_update_rejected, 1),
            ]
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            error = RuntimeError(
                f"failed to subscribe to shadow update topics (rc={result})"
            )
            with self._lock:
                self._connection_ready = False
                self._connection_error = error
            self._connection_done.set()

    def _on_subscribe(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _mid: int,
        _reason_codes: Any,
        _properties: Any,
    ) -> None:
        with self._lock:
            self._connection_ready = True
            self._connection_error = None
        self._connection_done.set()

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        with self._lock:
            self._connection_ready = False
        if not self._disconnect_requested:
            LOGGER.warning("AWS IoT MQTT disconnected unexpectedly (reason=%s)", reason_code)
            self._connection_done.set()

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            LOGGER.warning("Ignored non-JSON MQTT message on topic %s", msg.topic)
            return

        token = payload.get("clientToken")
        if not isinstance(token, str):
            return

        with self._lock:
            if token != self._pending_token:
                return

            if msg.topic == self._topic_update_accepted:
                self._pending_response = payload
            elif msg.topic == self._topic_update_rejected:
                self._pending_error = RuntimeError(
                    f"shadow update rejected: {json.dumps(payload, sort_keys=True)}"
                )
            else:
                return

        self._response_done.set()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Txing device-side Raspberry Pi board shadow reporter",
    )
    parser.add_argument(
        "--shadow-file",
        type=Path,
        default=DEFAULT_SHADOW_FILE,
        help="Path to local accepted shadow mirror file (default: /tmp/txing_board_shadow.json)",
    )
    parser.add_argument(
        "--thing-name",
        default=DEFAULT_THING_NAME,
        help="AWS IoT thing name (default: txing)",
    )
    parser.add_argument(
        "--iot-endpoint",
        default=None,
        help="AWS IoT data endpoint hostname; if omitted, --iot-endpoint-file is used",
    )
    parser.add_argument(
        "--iot-endpoint-file",
        type=Path,
        default=DEFAULT_IOT_ENDPOINT_FILE,
        help=f"File containing AWS IoT endpoint (default: {DEFAULT_IOT_ENDPOINT_FILE})",
    )
    parser.add_argument(
        "--cert-file",
        type=Path,
        default=DEFAULT_CERT_FILE,
        help=f"Client certificate PEM file (default: {DEFAULT_CERT_FILE})",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=DEFAULT_KEY_FILE,
        help=f"Client private key file (default: {DEFAULT_KEY_FILE})",
    )
    parser.add_argument(
        "--ca-file",
        type=Path,
        default=DEFAULT_CA_FILE,
        help=f"Root CA file (default: {DEFAULT_CA_FILE})",
    )
    parser.add_argument(
        "--schema-file",
        type=Path,
        default=DEFAULT_SCHEMA_FILE,
        help=f"Thing Shadow schema file (default: {DEFAULT_SCHEMA_FILE})",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="MQTT client id (default: txing-board-<hostname>-<pid>)",
    )
    parser.add_argument(
        "--board-name",
        default=socket.gethostname(),
        help="Reported board hostname/name (default: current hostname)",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help="Seconds between repeated reported.board updates (default: 60)",
    )
    parser.add_argument(
        "--aws-connect-timeout",
        type=float,
        default=DEFAULT_AWS_CONNECT_TIMEOUT,
        help="Seconds to wait for AWS MQTT connect + subscribe readiness (default: 20)",
    )
    parser.add_argument(
        "--publish-timeout",
        type=float,
        default=DEFAULT_MQTT_PUBLISH_TIMEOUT,
        help="Seconds to wait for shadow update accepted/rejected response (default: 10)",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=DEFAULT_RECONNECT_DELAY,
        help="Seconds to wait before reconnect after a publish failure (default: 5)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Publish a single reported.board update and exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def _configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{description} {path} does not exist")


def _read_iot_endpoint(endpoint: str | None, endpoint_file: Path) -> str:
    if endpoint is not None:
        value = endpoint.strip()
        if value:
            return value
        raise RuntimeError("--iot-endpoint was provided but is empty")
    try:
        value = endpoint_file.read_text(encoding="utf-8").strip()
    except OSError as err:
        raise RuntimeError(
            f"failed to read AWS IoT endpoint file {endpoint_file}: {err}"
        ) from err
    if not value:
        raise RuntimeError(f"AWS IoT endpoint file {endpoint_file} is empty")
    return value


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_optional_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    value = value.replace("\x00", "").strip()
    return value or None


def _read_boot_id() -> str | None:
    return _read_optional_text(Path("/proc/sys/kernel/random/boot_id"))


def _read_board_model() -> str | None:
    for path in (
        Path("/proc/device-tree/model"),
        Path("/sys/firmware/devicetree/base/model"),
    ):
        value = _read_optional_text(path)
        if value is not None:
            return value
    return None


def _read_uptime_seconds() -> int | None:
    value = _read_optional_text(Path("/proc/uptime"))
    if value is None:
        return None
    first, *_rest = value.split()
    try:
        uptime_seconds = float(first)
    except ValueError:
        return None
    if uptime_seconds < 0:
        return None
    return int(uptime_seconds)


def _package_version() -> str:
    try:
        return importlib.metadata.version("board")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def _sanitize_client_id(value: str) -> str:
    sanitized = []
    for char in value:
        if char.isalnum() or char in ("-", "_", ":"):
            sanitized.append(char)
        else:
            sanitized.append("-")
    result = "".join(sanitized).strip("-")
    return result or "board"


def _drop_none_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_drop_none_values(item) for item in value if item is not None]
    return value


def _build_board_report(
    config: ReporterConfig,
    *,
    started_at: str,
    online: bool,
) -> dict[str, Any]:
    report = {
        "online": online,
        "hostname": config.board_name,
        "model": _read_board_model(),
        "bootId": _read_boot_id(),
        "programVersion": _package_version(),
        "startedAt": started_at,
        "reportedAt": _utc_now_iso(),
        "uptimeSeconds": _read_uptime_seconds(),
        "clientId": config.client_id,
    }
    return _drop_none_values(report)


def _build_shadow_update(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": {
            "reported": {
                "board": report,
            }
        }
    }


def _load_validator(schema_file: Path) -> jsonschema.Draft202012Validator:
    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
    except OSError as err:
        raise RuntimeError(f"failed to read schema file {schema_file}: {err}") from err
    except json.JSONDecodeError as err:
        raise RuntimeError(f"schema file {schema_file} is not valid JSON: {err}") from err
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )


def _format_validation_path(error: jsonschema.ValidationError) -> str:
    if not error.absolute_path:
        return "<root>"
    return ".".join(str(part) for part in error.absolute_path)


def _validate_shadow_update(
    validator: jsonschema.Draft202012Validator,
    payload: dict[str, Any],
) -> None:
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if not errors:
        return
    first = errors[0]
    raise RuntimeError(
        f"shadow payload does not match {DEFAULT_SCHEMA_FILE.name} at {_format_validation_path(first)}: {first.message}"
    )


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)


def main() -> None:
    args = _parse_args()
    _configure_logging(args.debug)

    try:
        iot_endpoint = _read_iot_endpoint(args.iot_endpoint, args.iot_endpoint_file)
        _require_file(args.cert_file, "AWS IoT client certificate")
        _require_file(args.key_file, "AWS IoT client private key")
        _require_file(args.ca_file, "AWS IoT root CA")
        _require_file(args.schema_file, "Thing Shadow schema file")
        board_client_suffix = _sanitize_client_id(args.board_name)
        client_id = args.client_id or f"txing-board-{board_client_suffix}-{os.getpid()}"
        config = ReporterConfig(
            thing_name=args.thing_name,
            iot_endpoint=iot_endpoint,
            cert_file=args.cert_file,
            key_file=args.key_file,
            ca_file=args.ca_file,
            schema_file=args.schema_file,
            shadow_file=args.shadow_file,
            client_id=client_id,
            board_name=args.board_name,
            heartbeat_seconds=args.heartbeat_seconds,
            aws_connect_timeout=args.aws_connect_timeout,
            publish_timeout=args.publish_timeout,
            reconnect_delay=args.reconnect_delay,
            once=args.once,
        )
        validator = _load_validator(config.schema_file)
    except RuntimeError as err:
        print(f"board start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    started_at = _utc_now_iso()
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    LOGGER.info(
        "Board reporter started pid=%s thing=%s client_id=%s",
        os.getpid(),
        config.thing_name,
        config.client_id,
    )

    shadow_client = AwsShadowClient(config)

    try:
        while not stop_event.is_set():
            try:
                shadow_client.ensure_connected(timeout_seconds=config.aws_connect_timeout)
                report = _build_board_report(config, started_at=started_at, online=True)
                payload = _build_shadow_update(report)
                _validate_shadow_update(validator, payload)
                accepted = shadow_client.publish_update(
                    payload,
                    timeout_seconds=config.publish_timeout,
                )
                save_shadow(accepted, config.shadow_file)
                LOGGER.info(
                    "Published board shadow update online=%s uptimeSeconds=%s",
                    report.get("online"),
                    report.get("uptimeSeconds"),
                )
                if config.once:
                    break
                if stop_event.wait(config.heartbeat_seconds):
                    break
            except RuntimeError as err:
                LOGGER.warning("Board shadow publish failed: %s", err)
                if config.once:
                    raise SystemExit(1) from err
                if stop_event.wait(config.reconnect_delay):
                    break

        if stop_event.is_set() and not config.once and shadow_client.is_connected():
            try:
                report = _build_board_report(config, started_at=started_at, online=False)
                payload = _build_shadow_update(report)
                _validate_shadow_update(validator, payload)
                accepted = shadow_client.publish_update(
                    payload,
                    timeout_seconds=config.publish_timeout,
                )
                save_shadow(accepted, config.shadow_file)
                LOGGER.info("Published best-effort clean shutdown board update")
            except RuntimeError as err:
                LOGGER.warning("Failed to publish best-effort shutdown board update: %s", err)
    finally:
        shadow_client.close()
