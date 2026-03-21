from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import paho.mqtt.client as mqtt

from .media_state import DEFAULT_MEDIA_STATE_FILE, build_reported_media_state, load_media_state
from .shadow_store import DEFAULT_SHADOW_FILE, save_shadow

LOGGER = logging.getLogger("board.shadow_control")
MQTT_LOGGER = logging.getLogger("board.shadow_control.mqtt")

def _is_repo_root(path: Path) -> bool:
    return (
        (path / "board" / "pyproject.toml").is_file()
        and (path / "docs" / "txing-shadow.schema.json").is_file()
    )


def _discover_repo_root(
    *,
    cwd: Path,
    module_file: Path,
    env_repo_root: str | None,
) -> Path:
    if env_repo_root:
        return Path(env_repo_root).expanduser().resolve()

    resolved_cwd = cwd.resolve()
    seen: set[Path] = set()
    candidates = [resolved_cwd, *resolved_cwd.parents, *module_file.resolve().parents]
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _is_repo_root(candidate):
            return candidate
        if candidate.name == "board" and (candidate / "pyproject.toml").is_file():
            return candidate.parent

    return resolved_cwd.parent if resolved_cwd.name == "board" else resolved_cwd


REPO_ROOT = _discover_repo_root(
    cwd=Path.cwd(),
    module_file=Path(__file__),
    env_repo_root=os.environ.get("TXING_REPO_ROOT"),
)
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
DEFAULT_HALT_COMMAND = ("/usr/bin/systemctl", "halt", "--no-wall")
DEFAULT_ROUTE_PROBE_IPV4 = ("8.8.8.8", 80)
DEFAULT_ROUTE_PROBE_IPV6 = ("2001:4860:4860::8888", 80, 0, 0)


@dataclass(frozen=True)
class ControlConfig:
    thing_name: str
    iot_endpoint: str
    cert_file: Path
    key_file: Path
    ca_file: Path
    schema_file: Path
    shadow_file: Path
    media_state_file: Path
    client_id: str
    board_name: str
    heartbeat_seconds: float
    aws_connect_timeout: float
    publish_timeout: float
    reconnect_delay: float
    halt_command: tuple[str, ...]
    once: bool


@dataclass(frozen=True)
class DefaultRouteAddresses:
    ipv4: str | None
    ipv6: str | None


class AwsShadowClient:
    def __init__(self, config: ControlConfig) -> None:
        self._config = config
        self._topic_prefix = f"$aws/things/{config.thing_name}/shadow"
        self._topic_get = f"{self._topic_prefix}/get"
        self._topic_get_accepted = f"{self._topic_prefix}/get/accepted"
        self._topic_get_rejected = f"{self._topic_prefix}/get/rejected"
        self._topic_update = f"{self._topic_prefix}/update"
        self._topic_update_accepted = (
            f"{self._topic_prefix}/update/accepted"
        )
        self._topic_update_rejected = (
            f"{self._topic_prefix}/update/rejected"
        )
        self._topic_update_delta = f"{self._topic_prefix}/update/delta"
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
        self._halt_requested = threading.Event()
        self._desired_board_power: bool | None = None

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

    def halt_requested(self) -> bool:
        return self._halt_requested.is_set()

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
        if _reason_code_is_failure(reason_code):
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
                (self._topic_get_accepted, 1),
                (self._topic_get_rejected, 1),
                (self._topic_update_accepted, 1),
                (self._topic_update_rejected, 1),
                (self._topic_update_delta, 1),
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
        self._request_shadow_get()

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

        if msg.topic == self._topic_get_rejected:
            LOGGER.warning("Shadow get rejected: %s", json.dumps(payload, sort_keys=True))
            return

        if msg.topic == self._topic_get_accepted:
            self._observe_desired_board_power(
                _extract_desired_board_power_from_shadow(payload),
                source="shadow/get/accepted",
            )
            return

        if msg.topic == self._topic_update_delta:
            desired_power = _extract_desired_board_power_from_delta(payload)
            if desired_power is None:
                LOGGER.debug(
                    "Ignored shadow delta without desired.board.power: %s",
                    payload,
                )
                return
            self._observe_desired_board_power(
                desired_power,
                source="shadow/update/delta",
            )
            return

        if msg.topic == self._topic_update_accepted:
            self._observe_desired_board_power(
                _extract_desired_board_power_from_shadow(payload),
                source="shadow/update/accepted",
            )

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

    def _request_shadow_get(self) -> None:
        info = self._client.publish(self._topic_get, payload="{}", qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.warning(
                "Failed to request current shadow snapshot on %s (rc=%s)",
                self._topic_get,
                info.rc,
            )

    def _observe_desired_board_power(
        self,
        desired_power: bool | None,
        *,
        source: str,
    ) -> None:
        if desired_power is None:
            return

        with self._lock:
            previous = self._desired_board_power
            self._desired_board_power = desired_power

        if previous != desired_power:
            LOGGER.info(
                "Observed desired.board.power=%s from %s",
                desired_power,
                source,
            )

        if desired_power or self._halt_requested.is_set():
            return

        LOGGER.warning(
            "Desired board.power=false received from %s; preparing local halt",
            source,
        )
        self._halt_requested.set()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Txing device-side Raspberry Pi board control",
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
        "--media-state-file",
        type=Path,
        default=DEFAULT_MEDIA_STATE_FILE,
        help=f"Path to local board-media runtime state file (default: {DEFAULT_MEDIA_STATE_FILE})",
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
        help="Seconds between repeated reported.board.power/wifi updates (default: 60)",
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
        "--halt-command",
        nargs="+",
        default=list(DEFAULT_HALT_COMMAND),
        help=(
            "Command used when desired.board.power=false requests a local halt "
            "(default: /usr/bin/systemctl halt --no-wall)"
        ),
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


def _sanitize_client_id(value: str) -> str:
    sanitized = []
    for char in value:
        if char.isalnum() or char in ("-", "_", ":"):
            sanitized.append(char)
        else:
            sanitized.append("-")
    result = "".join(sanitized).strip("-")
    return result or "board"


def _normalize_ip_address(value: str) -> str | None:
    address_text = value.partition("%")[0].strip()
    if not address_text:
        return None
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError:
        return None
    if address.is_unspecified or address.is_loopback:
        return None
    return str(address)


def _detect_default_route_address(
    family: socket.AddressFamily,
    probe: tuple[Any, ...],
) -> str | None:
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            # UDP connect lets the OS choose the source address for the active route
            # without sending application data. That is portable across platforms and
            # avoids parsing route tables with OS-specific commands.
            sock.connect(probe)
            local_address = sock.getsockname()[0]
    except OSError:
        return None
    if not isinstance(local_address, str):
        return None
    return _normalize_ip_address(local_address)


def _detect_default_route_addresses() -> DefaultRouteAddresses:
    return DefaultRouteAddresses(
        ipv4=_detect_default_route_address(socket.AF_INET, DEFAULT_ROUTE_PROBE_IPV4),
        ipv6=_detect_default_route_address(socket.AF_INET6, DEFAULT_ROUTE_PROBE_IPV6),
    )


def _reason_code_is_failure(reason_code: Any) -> bool:
    is_failure = getattr(reason_code, "is_failure", None)
    if callable(is_failure):
        return bool(is_failure())
    if is_failure is not None:
        return bool(is_failure)
    return reason_code != 0


def _extract_desired_board_power_from_shadow(payload: dict[str, Any]) -> bool | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    desired = state.get("desired")
    if not isinstance(desired, dict):
        return None
    board = desired.get("board")
    if not isinstance(board, dict):
        return None
    value = board.get("power")
    return value if isinstance(value, bool) else None


def _extract_desired_board_power_from_delta(payload: dict[str, Any]) -> bool | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    board = state.get("board")
    if not isinstance(board, dict):
        return None
    value = board.get("power")
    return value if isinstance(value, bool) else None


def _build_board_report(
    *,
    addresses: DefaultRouteAddresses,
    power: bool,
    media_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "power": power,
        "wifi": {
            "online": power,
            "ipv4": addresses.ipv4,
            "ipv6": addresses.ipv6,
        },
    }
    if isinstance(media_state, dict):
        report["video"] = build_reported_media_state(media_state)
    return report


def _build_shutdown_board_report() -> dict[str, Any]:
    return {
        "power": False,
        "wifi": {
            "online": False,
            "ipv4": None,
            "ipv6": None,
        },
    }


def _build_shadow_update(report: dict[str, Any]) -> dict[str, Any]:
    return _build_shadow_update_with_options(report=report, clear_desired_power=False)


def _build_shadow_update_with_options(
    *,
    report: dict[str, Any],
    clear_desired_power: bool,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "reported": {
            "board": report,
        }
    }
    if clear_desired_power:
        state["desired"] = {
            "board": {
                "power": None,
            }
        }
    return {"state": state}


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


def _wait_for_stop_or_halt(
    stop_event: threading.Event,
    shadow_client: AwsShadowClient,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if stop_event.is_set() or shadow_client.halt_requested():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        stop_event.wait(min(0.5, remaining))


def _request_system_halt(command: tuple[str, ...]) -> None:
    command_text = shlex.join(command)
    LOGGER.warning("Requesting system halt via %s", command_text)
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as err:
        LOGGER.error("Failed to request system halt via %s: %s", command_text, err)


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
        config = ControlConfig(
            thing_name=args.thing_name,
            iot_endpoint=iot_endpoint,
            cert_file=args.cert_file,
            key_file=args.key_file,
            ca_file=args.ca_file,
            schema_file=args.schema_file,
            shadow_file=args.shadow_file,
            media_state_file=args.media_state_file,
            client_id=client_id,
            board_name=args.board_name,
            heartbeat_seconds=args.heartbeat_seconds,
            aws_connect_timeout=args.aws_connect_timeout,
            publish_timeout=args.publish_timeout,
            reconnect_delay=args.reconnect_delay,
            halt_command=tuple(args.halt_command),
            once=args.once,
        )
        validator = _load_validator(config.schema_file)
    except RuntimeError as err:
        print(f"board start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    LOGGER.info(
        "Board control started pid=%s thing=%s client_id=%s",
        os.getpid(),
        config.thing_name,
        config.client_id,
    )
    initial_addresses = _detect_default_route_addresses()
    LOGGER.info(
        "Initial default-route addresses ipv4=%s ipv6=%s",
        initial_addresses.ipv4 or "-",
        initial_addresses.ipv6 or "-",
    )

    shadow_client = AwsShadowClient(config)
    halt_requested = False

    try:
        while not stop_event.is_set() and not shadow_client.halt_requested():
            try:
                shadow_client.ensure_connected(timeout_seconds=config.aws_connect_timeout)
                default_route_addresses = _detect_default_route_addresses()
                media_state = load_media_state(config.media_state_file)
                report = _build_board_report(
                    addresses=default_route_addresses,
                    power=True,
                    media_state=media_state,
                )
                payload = _build_shadow_update(report)
                _validate_shadow_update(validator, payload)
                accepted = shadow_client.publish_update(
                    payload,
                    timeout_seconds=config.publish_timeout,
                )
                save_shadow(accepted, config.shadow_file)
                LOGGER.info(
                    (
                        "Published board shadow update power=%s wifi_online=%s ipv4=%s ipv6=%s "
                        "video_status=%s video_ready=%s viewer_url=%s"
                    ),
                    report.get("power"),
                    report.get("wifi", {}).get("online") if isinstance(report.get("wifi"), dict) else None,
                    report.get("wifi", {}).get("ipv4") if isinstance(report.get("wifi"), dict) else "-",
                    report.get("wifi", {}).get("ipv6") if isinstance(report.get("wifi"), dict) else "-",
                    report.get("video", {}).get("status") if isinstance(report.get("video"), dict) else "-",
                    report.get("video", {}).get("ready") if isinstance(report.get("video"), dict) else "-",
                    (
                        report.get("video", {}).get("local", {}).get("viewerUrl")
                        if isinstance(report.get("video", {}).get("local"), dict)
                        else "-"
                    ),
                )
                if config.once or shadow_client.halt_requested():
                    break
                if _wait_for_stop_or_halt(
                    stop_event,
                    shadow_client,
                    config.heartbeat_seconds,
                ):
                    break
            except RuntimeError as err:
                LOGGER.warning("Board shadow publish failed: %s", err)
                if config.once:
                    raise SystemExit(1) from err
                if _wait_for_stop_or_halt(
                    stop_event,
                    shadow_client,
                    config.reconnect_delay,
                ):
                    break

        halt_requested = shadow_client.halt_requested()
        if (stop_event.is_set() or halt_requested) and not config.once and shadow_client.is_connected():
            try:
                report = _build_shutdown_board_report()
                payload = _build_shadow_update_with_options(
                    report=report,
                    clear_desired_power=True,
                )
                _validate_shadow_update(validator, payload)
                accepted = shadow_client.publish_update(
                    payload,
                    timeout_seconds=config.publish_timeout,
                )
                save_shadow(accepted, config.shadow_file)
                LOGGER.info(
                    "Published best-effort clean shutdown board update and cleared desired.board.power"
                )
            except RuntimeError as err:
                LOGGER.warning("Failed to publish best-effort shutdown board update: %s", err)
    finally:
        shadow_client.close()

    if halt_requested:
        _request_system_halt(config.halt_command)
