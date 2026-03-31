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

from .cmd_vel import CmdVelController, DriveState, build_cmd_vel_topic
from .shadow_store import DEFAULT_SHADOW_FILE, save_shadow
from .video_sender import (
    DEFAULT_SENDER_COMMAND_ENV,
    VideoSenderSupervisor,
)
from .video_state import (
    DEFAULT_VIDEO_CHANNEL_NAME,
    DEFAULT_VIDEO_STATE_FILE,
    build_reported_video_state,
)

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
DEFAULT_DRIVE_REPORT_POLL_INTERVAL = 0.25
DEFAULT_RECONNECT_DELAY = 5.0
DEFAULT_TIME_SYNC_TIMEOUT = 120.0
DEFAULT_TIME_SYNC_POLL_INTERVAL = 1.0
DEFAULT_VIDEO_REGION = "eu-central-1"
DEFAULT_VIDEO_STARTUP_TIMEOUT_SECONDS = 30.0
DEFAULT_VIDEO_READY_POLL_INTERVAL = 0.5
DEFAULT_HALT_COMMAND = ("/usr/bin/systemctl", "halt", "--no-wall")
DEFAULT_TIMEDATECTL_SYNC_COMMAND = (
    "/usr/bin/timedatectl",
    "show",
    "--property=SystemClockSynchronized",
    "--value",
)
DEFAULT_ROUTE_PROBE_IPV4 = ("8.8.8.8", 80)
DEFAULT_ROUTE_PROBE_IPV6 = ("2001:4860:4860::8888", 80, 0, 0)
DEFAULT_THING_NAME_ENV = "THING_NAME"
DEFAULT_IOT_ENDPOINT_FILE_ENV = "IOT_ENDPOINT_FILE"
DEFAULT_CERT_FILE_ENV = "CERT_FILE"
DEFAULT_KEY_FILE_ENV = "KEY_FILE"
DEFAULT_CA_FILE_ENV = "CA_FILE"
DEFAULT_SCHEMA_FILE_ENV = "SCHEMA_FILE"
DEFAULT_VIDEO_CHANNEL_NAME_ENV = "BOARD_VIDEO_CHANNEL_NAME"
LEGACY_VIDEO_CHANNEL_NAME_ENV = "TXING_BOARD_VIDEO_CHANNEL_NAME"
DEFAULT_VIDEO_VIEWER_URL_ENV = "BOARD_VIDEO_VIEWER_URL"
DEFAULT_VIDEO_REGION_ENV = "BOARD_VIDEO_REGION"
LEGACY_VIDEO_REGION_ENV = "TXING_BOARD_VIDEO_REGION"


def _env_text(*names: str, default: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _env_optional_path(*names: str) -> Path | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value)
    return None


def _env_path(*names: str, default: Path) -> Path:
    resolved = _env_optional_path(*names)
    return resolved if resolved is not None else default


@dataclass(frozen=True)
class ControlConfig:
    thing_name: str
    iot_endpoint: str
    cert_file: Path
    key_file: Path
    ca_file: Path
    schema_file: Path
    shadow_file: Path
    client_id: str
    video_channel_name: str
    video_viewer_url: str
    video_region: str
    video_sender_command: str
    aws_shared_credentials_file: Path | None
    aws_config_file: Path | None
    video_startup_timeout_seconds: float
    board_name: str
    heartbeat_seconds: float
    aws_connect_timeout: float
    publish_timeout: float
    reconnect_delay: float
    time_sync_timeout_seconds: float
    halt_command: tuple[str, ...]
    once: bool


@dataclass(frozen=True)
class DefaultRouteAddresses:
    ipv4: str | None
    ipv6: str | None


class VideoStartupTimeoutError(RuntimeError):
    pass


class AwsShadowClient:
    def __init__(
        self,
        config: ControlConfig,
        *,
        cmd_vel_controller: CmdVelController | None = None,
    ) -> None:
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
        self._topic_cmd_vel = build_cmd_vel_topic(config.thing_name)
        self._cmd_vel_controller = cmd_vel_controller
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
                (self._topic_cmd_vel, 1),
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
        if self._cmd_vel_controller is not None:
            self._cmd_vel_controller.handle_disconnect(
                f"AWS IoT MQTT disconnect reason={reason_code}"
            )
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

        if msg.topic == self._topic_cmd_vel:
            if self._cmd_vel_controller is not None:
                self._cmd_vel_controller.handle_message(payload)
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
        default=_env_text(DEFAULT_THING_NAME_ENV, default=DEFAULT_THING_NAME),
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
        default=_env_path(DEFAULT_IOT_ENDPOINT_FILE_ENV, default=DEFAULT_IOT_ENDPOINT_FILE),
        help=f"File containing AWS IoT endpoint (default: {DEFAULT_IOT_ENDPOINT_FILE})",
    )
    parser.add_argument(
        "--cert-file",
        type=Path,
        default=_env_path(DEFAULT_CERT_FILE_ENV, default=DEFAULT_CERT_FILE),
        help=f"Client certificate PEM file (default: {DEFAULT_CERT_FILE})",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=_env_path(DEFAULT_KEY_FILE_ENV, default=DEFAULT_KEY_FILE),
        help=f"Client private key file (default: {DEFAULT_KEY_FILE})",
    )
    parser.add_argument(
        "--ca-file",
        type=Path,
        default=_env_path(DEFAULT_CA_FILE_ENV, default=DEFAULT_CA_FILE),
        help=f"Root CA file (default: {DEFAULT_CA_FILE})",
    )
    parser.add_argument(
        "--schema-file",
        type=Path,
        default=_env_path(DEFAULT_SCHEMA_FILE_ENV, default=DEFAULT_SCHEMA_FILE),
        help=f"Thing Shadow schema file (default: {DEFAULT_SCHEMA_FILE})",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="MQTT client id (default: txing-board-<hostname>-<pid>)",
    )
    parser.add_argument(
        "--video-channel-name",
        default=_env_text(
            DEFAULT_VIDEO_CHANNEL_NAME_ENV,
            LEGACY_VIDEO_CHANNEL_NAME_ENV,
            default=DEFAULT_VIDEO_CHANNEL_NAME,
        ),
        help=f"AWS KVS signaling channel name (default: {DEFAULT_VIDEO_CHANNEL_NAME})",
    )
    parser.add_argument(
        "--video-viewer-url",
        default=_env_text(DEFAULT_VIDEO_VIEWER_URL_ENV, default=""),
        help="Published operator-facing browser URL for the board video route",
    )
    parser.add_argument(
        "--video-sender-command",
        default=os.environ.get(DEFAULT_SENDER_COMMAND_ENV, ""),
        help=(
            "Command that runs the actual KVS master sender "
            f"(default: ${DEFAULT_SENDER_COMMAND_ENV})"
        ),
    )
    parser.add_argument(
        "--video-region",
        default=_env_text(
            DEFAULT_VIDEO_REGION_ENV,
            LEGACY_VIDEO_REGION_ENV,
            default=DEFAULT_VIDEO_REGION,
        ),
        help=f"AWS region for the board video signaling channel (default: {DEFAULT_VIDEO_REGION})",
    )
    parser.add_argument(
        "--aws-shared-credentials-file",
        type=Path,
        default=_env_optional_path("AWS_SHARED_CREDENTIALS_FILE"),
        help=(
            "AWS shared credentials file passed through to the board video sender "
            "(default: $AWS_SHARED_CREDENTIALS_FILE or SDK default chain)"
        ),
    )
    parser.add_argument(
        "--aws-config-file",
        type=Path,
        default=_env_optional_path("AWS_CONFIG_FILE"),
        help=(
            "AWS config file passed through to the board video sender "
            "(default: $AWS_CONFIG_FILE or SDK default chain)"
        ),
    )
    parser.add_argument(
        "--video-startup-timeout-seconds",
        type=float,
        default=DEFAULT_VIDEO_STARTUP_TIMEOUT_SECONDS,
        help=(
            "Seconds to wait for board video sender readiness before the first shadow publish "
            f"(default: {DEFAULT_VIDEO_STARTUP_TIMEOUT_SECONDS})"
        ),
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
        "--time-sync-timeout-seconds",
        type=float,
        default=DEFAULT_TIME_SYNC_TIMEOUT,
        help=(
            "Seconds to wait for system clock synchronization before starting AWS video "
            f"startup (default: {DEFAULT_TIME_SYNC_TIMEOUT})"
        ),
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


def _require_non_empty_option(value: str, option_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise RuntimeError(f"{option_name} must not be empty")
    return stripped


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
    drive_state: DriveState,
    video_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "power": power,
        "wifi": {
            "online": power,
            "ipv4": addresses.ipv4,
            "ipv6": addresses.ipv6,
        },
        "drive": {
            "leftSpeed": drive_state.left_speed,
            "rightSpeed": drive_state.right_speed,
        },
    }
    if isinstance(video_state, dict):
        report["video"] = build_reported_video_state(video_state)
    return report


def _build_shutdown_board_report() -> dict[str, Any]:
    return {
        "power": False,
        "wifi": {
            "online": False,
            "ipv4": None,
            "ipv6": None,
        },
        "drive": {
            "leftSpeed": 0,
            "rightSpeed": 0,
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


def _read_video_state(
    video_supervisor: VideoSenderSupervisor,
) -> dict[str, Any]:
    return video_supervisor.read_state()


def _query_system_clock_synchronized() -> bool | None:
    try:
        completed = subprocess.run(
            DEFAULT_TIMEDATECTL_SYNC_COMMAND,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    value = completed.stdout.strip().lower()
    if value in {"yes", "true", "1"}:
        return True
    if value in {"no", "false", "0"}:
        return False
    return None


def _wait_for_system_clock_sync(
    stop_event: threading.Event,
    timeout_seconds: float,
) -> None:
    if timeout_seconds <= 0:
        return

    synchronized = _query_system_clock_synchronized()
    if synchronized is None:
        LOGGER.warning(
            "Could not determine system clock sync state via timedatectl; proceeding without an explicit clock-sync gate"
        )
        return
    if synchronized:
        return

    LOGGER.info(
        "Waiting for system clock synchronization before AWS startup timeout=%.1fs",
        timeout_seconds,
    )
    deadline = time.monotonic() + timeout_seconds
    while True:
        if stop_event.is_set():
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"timed out waiting for system clock synchronization after {timeout_seconds:.1f}s; "
                "check timedatectl status and NTP"
            )

        stop_event.wait(min(DEFAULT_TIME_SYNC_POLL_INTERVAL, remaining))
        synchronized = _query_system_clock_synchronized()
        if synchronized is None:
            LOGGER.warning(
                "Could not determine system clock sync state via timedatectl while waiting; proceeding without an explicit clock-sync gate"
            )
            return
        if synchronized:
            LOGGER.info("System clock synchronized; continuing board startup")
            return


def _wait_for_video_ready(
    stop_event: threading.Event,
    shadow_client: AwsShadowClient,
    config: ControlConfig,
    video_supervisor: VideoSenderSupervisor,
) -> tuple[DefaultRouteAddresses, dict[str, Any]] | None:
    deadline = time.monotonic() + config.video_startup_timeout_seconds
    last_error: str | None = None
    video_supervisor.start()
    LOGGER.info(
        "Waiting for board video sender readiness before first shadow publish timeout=%.1fs",
        config.video_startup_timeout_seconds,
    )
    while True:
        if stop_event.is_set() or shadow_client.halt_requested():
            return None

        default_route_addresses = _detect_default_route_addresses()
        video_state = _read_video_state(video_supervisor)
        if video_state.get("ready") is True:
            LOGGER.info(
                "Board video sender ready for first shadow publish viewer_url=%s channel_name=%s",
                (
                    video_state.get("session", {}).get("viewerUrl")
                    if isinstance(video_state.get("session"), dict)
                    else "-"
                ),
                (
                    video_state.get("session", {}).get("channelName")
                    if isinstance(video_state.get("session"), dict)
                    else "-"
                ),
            )
            return default_route_addresses, video_state

        last_error_value = video_state.get("lastError")
        if isinstance(last_error_value, str) and last_error_value:
            last_error = last_error_value

        if video_supervisor.return_code() is not None:
            detail = last_error or f"video sender process exited with code {video_supervisor.return_code()}"
            raise VideoStartupTimeoutError(detail)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = last_error or "video sender did not report ready"
            raise VideoStartupTimeoutError(
                f"timed out waiting for video sender readiness after {config.video_startup_timeout_seconds:.1f}s: {detail}"
            )
        stop_event.wait(min(DEFAULT_VIDEO_READY_POLL_INTERVAL, remaining))


def _publish_board_report(
    *,
    shadow_client: AwsShadowClient,
    validator: jsonschema.Draft202012Validator,
    config: ControlConfig,
    report: dict[str, Any],
    clear_desired_power: bool = False,
) -> dict[str, Any]:
    payload = _build_shadow_update_with_options(
        report=report,
        clear_desired_power=clear_desired_power,
    )
    _validate_shadow_update(validator, payload)
    accepted = shadow_client.publish_update(
        payload,
        timeout_seconds=config.publish_timeout,
    )
    save_shadow(accepted, config.shadow_file)
    return accepted


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
        video_viewer_url = _require_non_empty_option(
            args.video_viewer_url,
            "--video-viewer-url",
        )
        video_sender_command = _require_non_empty_option(
            args.video_sender_command,
            "--video-sender-command",
        )
        video_region = _require_non_empty_option(
            args.video_region,
            "--video-region",
        )
        video_channel_name = _require_non_empty_option(
            args.video_channel_name,
            "--video-channel-name",
        )
        if args.aws_shared_credentials_file is not None:
            _require_file(args.aws_shared_credentials_file, "AWS shared credentials file")
        if args.aws_config_file is not None:
            _require_file(args.aws_config_file, "AWS config file")
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
            client_id=client_id,
            video_channel_name=video_channel_name,
            video_viewer_url=video_viewer_url,
            video_region=video_region,
            video_sender_command=video_sender_command,
            aws_shared_credentials_file=args.aws_shared_credentials_file,
            aws_config_file=args.aws_config_file,
            video_startup_timeout_seconds=args.video_startup_timeout_seconds,
            board_name=args.board_name,
            heartbeat_seconds=args.heartbeat_seconds,
            aws_connect_timeout=args.aws_connect_timeout,
            publish_timeout=args.publish_timeout,
            reconnect_delay=args.reconnect_delay,
            time_sync_timeout_seconds=args.time_sync_timeout_seconds,
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

    cmd_vel_controller = CmdVelController(thing_name=config.thing_name)
    cmd_vel_controller.start()
    shadow_client = AwsShadowClient(
        config,
        cmd_vel_controller=cmd_vel_controller,
    )
    video_supervisor = VideoSenderSupervisor(
        channel_name=config.video_channel_name,
        viewer_url=config.video_viewer_url,
        region=config.video_region,
        sender_command=config.video_sender_command,
        aws_shared_credentials_file=config.aws_shared_credentials_file,
        aws_config_file=config.aws_config_file,
        ca_file=config.ca_file,
        state_file=DEFAULT_VIDEO_STATE_FILE,
    )
    halt_requested = False
    startup_published = False
    last_published_drive_state: DriveState | None = None
    last_published_video_report: dict[str, Any] | None = None
    last_shadow_publish_monotonic: float | None = None

    try:
        while not stop_event.is_set() and not shadow_client.halt_requested() and not startup_published:
            try:
                _wait_for_system_clock_sync(
                    stop_event,
                    config.time_sync_timeout_seconds,
                )
                shadow_client.ensure_connected(timeout_seconds=config.aws_connect_timeout)
                video_ready = _wait_for_video_ready(
                    stop_event,
                    shadow_client,
                    config,
                    video_supervisor,
                )
                if video_ready is None:
                    break
                default_route_addresses, video_state = video_ready
                drive_state = cmd_vel_controller.get_drive_state()
                report = _build_board_report(
                    addresses=default_route_addresses,
                    power=True,
                    drive_state=drive_state,
                    video_state=video_state,
                )
                _publish_board_report(
                    shadow_client=shadow_client,
                    validator=validator,
                    config=config,
                    report=report,
                )
                LOGGER.info(
                    (
                        "Published board shadow update power=%s wifi_online=%s ipv4=%s ipv6=%s "
                        "drive_left=%s drive_right=%s video_status=%s video_ready=%s viewer_url=%s"
                    ),
                    report.get("power"),
                    report.get("wifi", {}).get("online") if isinstance(report.get("wifi"), dict) else None,
                    report.get("wifi", {}).get("ipv4") if isinstance(report.get("wifi"), dict) else "-",
                    report.get("wifi", {}).get("ipv6") if isinstance(report.get("wifi"), dict) else "-",
                    report.get("drive", {}).get("leftSpeed") if isinstance(report.get("drive"), dict) else "-",
                    report.get("drive", {}).get("rightSpeed") if isinstance(report.get("drive"), dict) else "-",
                    report.get("video", {}).get("status") if isinstance(report.get("video"), dict) else "-",
                    report.get("video", {}).get("ready") if isinstance(report.get("video"), dict) else "-",
                    (
                        report.get("video", {}).get("session", {}).get("viewerUrl")
                        if isinstance(report.get("video", {}).get("session"), dict)
                        else "-"
                    ),
                )
                startup_published = True
                last_published_drive_state = drive_state
                last_published_video_report = report.get("video") if isinstance(report.get("video"), dict) else None
                last_shadow_publish_monotonic = time.monotonic()
                if config.once:
                    break
            except VideoStartupTimeoutError as err:
                LOGGER.error("Board startup failed: %s", err)
                raise SystemExit(1) from err
            except RuntimeError as err:
                LOGGER.warning("Board startup publish failed: %s", err)
                if config.once:
                    raise SystemExit(1) from err
                if _wait_for_stop_or_halt(
                    stop_event,
                    shadow_client,
                    config.reconnect_delay,
                ):
                    break

        while (
            startup_published
            and not config.once
            and not stop_event.is_set()
            and not shadow_client.halt_requested()
        ):
            if last_shadow_publish_monotonic is None:
                heartbeat_due = True
                heartbeat_remaining = 0.0
            else:
                elapsed_since_publish = time.monotonic() - last_shadow_publish_monotonic
                heartbeat_due = elapsed_since_publish >= config.heartbeat_seconds
                heartbeat_remaining = max(0.0, config.heartbeat_seconds - elapsed_since_publish)

            current_drive_state = cmd_vel_controller.get_drive_state()
            current_video_state = _read_video_state(video_supervisor)
            current_video_report = (
                build_reported_video_state(current_video_state)
                if isinstance(current_video_state, dict)
                else None
            )
            drive_changed = (
                last_published_drive_state is None
                or current_drive_state.sequence != last_published_drive_state.sequence
            )
            video_changed = current_video_report != last_published_video_report

            if not heartbeat_due and not drive_changed and not video_changed:
                wait_seconds = min(DEFAULT_DRIVE_REPORT_POLL_INTERVAL, heartbeat_remaining)
                if _wait_for_stop_or_halt(
                    stop_event,
                    shadow_client,
                    wait_seconds,
                ):
                    break
                continue

            try:
                shadow_client.ensure_connected(timeout_seconds=config.aws_connect_timeout)
                video_supervisor.ensure_running()
                default_route_addresses = _detect_default_route_addresses()
                report = _build_board_report(
                    addresses=default_route_addresses,
                    power=True,
                    drive_state=current_drive_state,
                    video_state=current_video_state,
                )
                _publish_board_report(
                    shadow_client=shadow_client,
                    validator=validator,
                    config=config,
                    report=report,
                )
                LOGGER.info(
                    (
                        "Published board shadow update power=%s wifi_online=%s ipv4=%s ipv6=%s "
                        "drive_left=%s drive_right=%s video_status=%s video_ready=%s viewer_url=%s"
                    ),
                    report.get("power"),
                    report.get("wifi", {}).get("online") if isinstance(report.get("wifi"), dict) else None,
                    report.get("wifi", {}).get("ipv4") if isinstance(report.get("wifi"), dict) else "-",
                    report.get("wifi", {}).get("ipv6") if isinstance(report.get("wifi"), dict) else "-",
                    report.get("drive", {}).get("leftSpeed") if isinstance(report.get("drive"), dict) else "-",
                    report.get("drive", {}).get("rightSpeed") if isinstance(report.get("drive"), dict) else "-",
                    report.get("video", {}).get("status") if isinstance(report.get("video"), dict) else "-",
                    report.get("video", {}).get("ready") if isinstance(report.get("video"), dict) else "-",
                    (
                        report.get("video", {}).get("session", {}).get("viewerUrl")
                        if isinstance(report.get("video", {}).get("session"), dict)
                        else "-"
                    ),
                )
                last_published_drive_state = current_drive_state
                last_published_video_report = report.get("video") if isinstance(report.get("video"), dict) else None
                last_shadow_publish_monotonic = time.monotonic()
            except RuntimeError as err:
                LOGGER.warning("Board shadow publish failed: %s", err)
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
                _publish_board_report(
                    shadow_client=shadow_client,
                    validator=validator,
                    config=config,
                    report=report,
                    clear_desired_power=True,
                )
                LOGGER.info(
                    "Published best-effort clean shutdown board update and cleared desired.board.power"
                )
            except RuntimeError as err:
                LOGGER.warning("Failed to publish best-effort shutdown board update: %s", err)
    finally:
        video_supervisor.stop()
        shadow_client.close()
        cmd_vel_controller.close()

    if halt_requested:
        _request_system_halt(config.halt_command)
