from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import os
from typing import Any, Mapping

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - deployment dependency
    boto3 = None

    class ClientError(Exception):  # type: ignore[no-redef]
        pass


SCHEMA_VERSION = "1.0"
TIME_TOPIC_NAMESPACE = "txings"
TIME_SERVICE_NAME = "time"
MCP_SERVICE_NAME = "mcp"
MCP_PROTOCOL_VERSION = "2025-11-25"
TIME_MODE_SLEEP = "sleep"
TIME_MODE_ACTIVE = "active"
COMMAND_STATUS_SUCCEEDED = "succeeded"
COMMAND_STATUS_FAILED = "failed"
DEFAULT_ACTIVE_TTL_MS = 300_000
DEFAULT_LEASE_TTL_MS = 5_000
DEFAULT_SERVER_VERSION = "0.5.0"
TIME_DEVICE_SEARCH_QUERY = "thingTypeName:time AND attributes.kind:deviceType"
TIME_DEVICE_SEARCH_PAGE_SIZE = 100

LOGGER = logging.getLogger(__name__)


def utc_now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def utc_iso(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def _segment(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    if "/" in text or "+" in text or "#" in text:
        raise ValueError(f"{field_name} must be a literal MQTT segment")
    return text


def build_time_topic_root(thing_name: str) -> str:
    return f"{TIME_TOPIC_NAMESPACE}/{_segment(thing_name, field_name='thing_name')}/{TIME_SERVICE_NAME}"


def build_time_command_topic(thing_name: str) -> str:
    return f"{build_time_topic_root(thing_name)}/command"


def build_time_state_topic(thing_name: str) -> str:
    return f"{build_time_topic_root(thing_name)}/state"


def build_time_command_result_topic(thing_name: str) -> str:
    return f"{build_time_topic_root(thing_name)}/command-result"


def build_mcp_topic_root(thing_name: str) -> str:
    return f"{TIME_TOPIC_NAMESPACE}/{_segment(thing_name, field_name='thing_name')}/{MCP_SERVICE_NAME}"


def build_mcp_descriptor_topic(thing_name: str) -> str:
    return f"{build_mcp_topic_root(thing_name)}/descriptor"


def build_mcp_status_topic(thing_name: str) -> str:
    return f"{build_mcp_topic_root(thing_name)}/status"


def build_mcp_session_s2c_topic(thing_name: str, session_id: str) -> str:
    return (
        f"{build_mcp_topic_root(thing_name)}/session/"
        f"{_segment(session_id, field_name='session_id')}/s2c"
    )


def parse_mcp_session_c2s_topic(topic: str) -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) != 6:
        return None
    if parts[0] != TIME_TOPIC_NAMESPACE or parts[2] != MCP_SERVICE_NAME:
        return None
    if parts[3] != "session" or parts[5] != "c2s":
        return None
    if not parts[1] or not parts[4]:
        return None
    return parts[1], parts[4]


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _json_loads(payload: bytes | str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    decoded = json.loads(payload)
    if not isinstance(decoded, Mapping):
        raise ValueError("payload must be a JSON object")
    return decoded


def _read_payload_body(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    read = getattr(value, "read", None)
    if callable(read):
        read_value = read()
        if isinstance(read_value, str):
            return read_value.encode("utf-8")
        return bytes(read_value)
    return json.dumps(value).encode("utf-8")


@dataclass(slots=True, frozen=True)
class ConnectivityCommand:
    command_id: str
    thing_name: str
    power: bool
    reason: str
    issued_at_ms: int
    deadline_ms: int | None
    seq: int = 0

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> ConnectivityCommand:
        decoded = _json_loads(payload)
        if decoded.get("schemaVersion") != SCHEMA_VERSION:
            raise ValueError("schemaVersion must be '1.0'")
        target = decoded.get("target")
        if not isinstance(target, Mapping):
            raise ValueError("target must be an object")
        power = target.get("power")
        if not isinstance(power, bool):
            raise ValueError("target.power must be a boolean")
        command_id = decoded.get("commandId")
        thing_name = decoded.get("thingName")
        reason = decoded.get("reason")
        issued_at_ms = decoded.get("issuedAtMs")
        deadline_ms = decoded.get("deadlineMs")
        seq = decoded.get("seq")
        if not isinstance(command_id, str) or not command_id.strip():
            raise ValueError("commandId must be a non-empty string")
        if not isinstance(thing_name, str) or not thing_name.strip():
            raise ValueError("thingName must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        if isinstance(issued_at_ms, bool) or not isinstance(issued_at_ms, int):
            raise ValueError("issuedAtMs must be an integer")
        if deadline_ms is not None and (
            isinstance(deadline_ms, bool) or not isinstance(deadline_ms, int)
        ):
            raise ValueError("deadlineMs must be an integer or null")
        if seq is not None and (isinstance(seq, bool) or not isinstance(seq, int)):
            raise ValueError("seq must be an integer")
        return cls(
            command_id=command_id.strip(),
            thing_name=thing_name.strip(),
            power=power,
            reason=reason.strip(),
            issued_at_ms=issued_at_ms,
            deadline_ms=deadline_ms,
            seq=seq or 0,
        )


@dataclass(slots=True)
class StoredTimeState:
    thing_name: str
    mode: str = TIME_MODE_SLEEP
    active_until_ms: int | None = None
    last_command_id: str | None = None
    seq: int = 0

    @classmethod
    def from_reported_shadow(
        cls,
        thing_name: str,
        reported: Mapping[str, Any] | None,
    ) -> StoredTimeState:
        reported = reported or {}
        mode = reported.get("mode")
        active_until_ms = reported.get("activeUntilMs")
        last_command_id = reported.get("lastCommandId")
        seq = reported.get("seq")
        return cls(
            thing_name=thing_name,
            mode=mode if mode == TIME_MODE_ACTIVE else TIME_MODE_SLEEP,
            active_until_ms=int(active_until_ms) if active_until_ms is not None else None,
            last_command_id=last_command_id if isinstance(last_command_id, str) else None,
            seq=int(seq) if seq is not None else 0,
        )


class TimeDeviceRuntime:
    def __init__(
        self,
        *,
        thing_name: str,
        iot_data_client: Any,
        active_ttl_ms: int = DEFAULT_ACTIVE_TTL_MS,
        server_version: str = DEFAULT_SERVER_VERSION,
    ) -> None:
        self.thing_name = _segment(thing_name, field_name="thing_name")
        self.iot_data_client = iot_data_client
        self.active_ttl_ms = int(active_ttl_ms)
        self.server_version = server_version

    def handle_scheduled_wake(self, event: Mapping[str, Any] | None = None) -> dict[str, Any]:
        del event
        now_ms = utc_now_ms()
        current_time_iso = utc_iso(now_ms)
        state = self.load_state()
        command = self.load_retained_command()

        command_result: dict[str, Any] | None = None
        if command and command.thing_name == self.thing_name:
            if command.command_id == state.last_command_id:
                command = None
            elif command.deadline_ms is not None and command.deadline_ms < now_ms:
                command = None
            else:
                state.last_command_id = command.command_id
                state.seq += 1
                if command.power:
                    state.mode = TIME_MODE_ACTIVE
                    state.active_until_ms = now_ms + self.active_ttl_ms
                else:
                    state.mode = TIME_MODE_SLEEP
                    state.active_until_ms = None
                command_result = self.build_command_result(
                    command=command,
                    status=COMMAND_STATUS_SUCCEEDED,
                    message=None,
                    now_ms=now_ms,
                    seq=state.seq,
                )

        if state.mode == TIME_MODE_ACTIVE and state.active_until_ms is not None:
            if state.active_until_ms <= now_ms:
                state.mode = TIME_MODE_SLEEP
                state.active_until_ms = None
                state.seq += 1

        mcp_available = state.mode == TIME_MODE_ACTIVE
        self.publish_time_state(state, current_time_iso=current_time_iso, now_ms=now_ms)
        self.publish_mcp_discovery(mcp_available=mcp_available, now_ms=now_ms)
        self.update_time_shadow(state, current_time_iso=current_time_iso, now_ms=now_ms)
        self.update_mcp_shadow(mcp_available=mcp_available, now_ms=now_ms)
        if command_result is not None:
            self.publish_command_result(command_result)

        return {
            "thingName": self.thing_name,
            "currentTimeIso": current_time_iso,
            "mode": state.mode,
            "activeUntilMs": state.active_until_ms,
            "lastCommandId": state.last_command_id,
            "mcpAvailable": mcp_available,
        }

    def handle_mcp_message(self, event: Mapping[str, Any]) -> dict[str, Any]:
        topic = event.get("mqttTopic")
        if not isinstance(topic, str):
            raise ValueError("MCP event is missing mqttTopic")
        parsed_topic = parse_mcp_session_c2s_topic(topic)
        if parsed_topic is None:
            raise ValueError(f"unsupported MCP topic: {topic}")
        thing_name, session_id = parsed_topic
        if thing_name != self.thing_name:
            raise ValueError(f"MCP topic thing={thing_name} does not match {self.thing_name}")
        message = self.decode_mcp_event_message(event)
        now_ms = utc_now_ms()
        state = self.load_state()
        active = state.mode == TIME_MODE_ACTIVE and (
            state.active_until_ms is None or state.active_until_ms > now_ms
        )
        if state.mode == TIME_MODE_ACTIVE and state.active_until_ms is not None:
            if state.active_until_ms <= now_ms:
                state.mode = TIME_MODE_SLEEP
                state.active_until_ms = None
                state.seq += 1
                current_time_iso = utc_iso(now_ms)
                self.publish_time_state(state, current_time_iso=current_time_iso, now_ms=now_ms)
                self.publish_mcp_discovery(mcp_available=False, now_ms=now_ms)
                self.update_time_shadow(state, current_time_iso=current_time_iso, now_ms=now_ms)
                self.update_mcp_shadow(mcp_available=False, now_ms=now_ms)
                active = False

        response = self.build_mcp_response(message, active=active, now_ms=now_ms)
        if response is not None:
            self.publish_mcp_response(session_id=session_id, response=response)
        return {
            "thingName": self.thing_name,
            "sessionId": session_id,
            "active": active,
            "responded": response is not None,
        }

    def load_state(self) -> StoredTimeState:
        try:
            response = self.iot_data_client.get_thing_shadow(
                thingName=self.thing_name,
                shadowName="time",
            )
        except ClientError as err:
            error_code = err.response.get("Error", {}).get("Code", "")
            if error_code in {"ResourceNotFoundException", "NotFoundException"}:
                return StoredTimeState(thing_name=self.thing_name)
            raise
        payload = _json_loads(_read_payload_body(response.get("payload")))
        state = payload.get("state")
        reported = state.get("reported") if isinstance(state, Mapping) else None
        if not isinstance(reported, Mapping):
            reported = None
        return StoredTimeState.from_reported_shadow(self.thing_name, reported)

    def load_retained_command(self) -> ConnectivityCommand | None:
        try:
            response = self.iot_data_client.get_retained_message(
                topic=build_time_command_topic(self.thing_name)
            )
        except ClientError as err:
            error_code = err.response.get("Error", {}).get("Code", "")
            if error_code in {"ResourceNotFoundException", "NotFoundException"}:
                return None
            raise
        payload = _read_payload_body(response.get("payload"))
        if not payload:
            return None
        return ConnectivityCommand.from_payload(payload)

    def publish_time_state(
        self,
        state: StoredTimeState,
        *,
        current_time_iso: str,
        now_ms: int,
    ) -> None:
        payload = {
            "thingName": self.thing_name,
            "currentTimeIso": current_time_iso,
            "mode": state.mode,
            "activeUntilMs": state.active_until_ms,
            "lastCommandId": state.last_command_id,
            "observedAtMs": now_ms,
            "mcpAvailable": state.mode == TIME_MODE_ACTIVE,
        }
        self.publish_json(
            build_time_state_topic(self.thing_name),
            payload,
            retain=True,
        )

    def publish_mcp_discovery(self, *, mcp_available: bool, now_ms: int) -> None:
        self.publish_json(
            build_mcp_descriptor_topic(self.thing_name),
            self.build_mcp_descriptor(),
            retain=True,
        )
        self.publish_json(
            build_mcp_status_topic(self.thing_name),
            self.build_mcp_status(mcp_available=mcp_available, now_ms=now_ms),
            retain=True,
        )

    def publish_command_result(self, payload: Mapping[str, Any]) -> None:
        self.publish_json(
            build_time_command_result_topic(self.thing_name),
            payload,
            retain=True,
        )

    def publish_mcp_response(self, *, session_id: str, response: Mapping[str, Any]) -> None:
        self.publish_json(
            build_mcp_session_s2c_topic(self.thing_name, session_id),
            response,
            retain=False,
        )

    def publish_json(self, topic: str, payload: Mapping[str, Any], *, retain: bool) -> None:
        self.iot_data_client.publish(
            topic=topic,
            qos=1,
            retain=retain,
            payload=_json_dumps(payload).encode("utf-8"),
        )

    def update_time_shadow(
        self,
        state: StoredTimeState,
        *,
        current_time_iso: str,
        now_ms: int,
    ) -> None:
        self.update_named_shadow(
            "time",
            {
                "state": {
                    "reported": {
                        "currentTimeIso": current_time_iso,
                        "mode": state.mode,
                        "activeUntilMs": state.active_until_ms,
                        "lastCommandId": state.last_command_id,
                        "observedAtMs": now_ms,
                        "seq": state.seq,
                    }
                }
            },
        )

    def update_mcp_shadow(self, *, mcp_available: bool, now_ms: int) -> None:
        self.update_named_shadow(
            "mcp",
            {
                "state": {
                    "reported": {
                        "descriptor": self.build_mcp_descriptor(),
                        "status": self.build_mcp_status(
                            mcp_available=mcp_available,
                            now_ms=now_ms,
                        ),
                    }
                }
            },
        )

    def update_named_shadow(self, shadow_name: str, payload: Mapping[str, Any]) -> None:
        self.iot_data_client.update_thing_shadow(
            thingName=self.thing_name,
            shadowName=shadow_name,
            payload=_json_dumps(payload).encode("utf-8"),
        )

    def build_mcp_descriptor(self) -> dict[str, Any]:
        topic_root = build_mcp_topic_root(self.thing_name)
        session_topic_pattern = {
            "clientToServer": f"{topic_root}/session/{{sessionId}}/c2s",
            "serverToClient": f"{topic_root}/session/{{sessionId}}/s2c",
        }
        return {
            "serviceId": MCP_SERVICE_NAME,
            "serverInfo": {
                "name": "time",
                "version": self.server_version,
            },
            "transport": "mqtt-jsonrpc",
            "mcpProtocolVersion": MCP_PROTOCOL_VERSION,
            "topicRoot": topic_root,
            "descriptorTopic": build_mcp_descriptor_topic(self.thing_name),
            "sessionTopicPattern": session_topic_pattern,
            "transports": [
                {
                    "type": "mqtt-jsonrpc",
                    "priority": 100,
                    "topicRoot": topic_root,
                    "sessionTopicPattern": session_topic_pattern,
                }
            ],
            "leaseRequired": False,
            "leaseTtlMs": DEFAULT_LEASE_TTL_MS,
            "serverVersion": self.server_version,
        }

    def build_mcp_status(self, *, mcp_available: bool, now_ms: int) -> dict[str, Any]:
        return {
            "serviceId": MCP_SERVICE_NAME,
            "available": bool(mcp_available),
            "updatedAtMs": int(now_ms),
        }

    def build_command_result(
        self,
        *,
        command: ConnectivityCommand,
        status: str,
        message: str | None,
        now_ms: int,
        seq: int,
    ) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "adapterId": "time-lambda",
            "commandId": command.command_id,
            "thingName": self.thing_name,
            "status": status,
            "message": message,
            "observedAtMs": now_ms,
            "seq": int(seq),
        }

    def decode_mcp_event_message(self, event: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            return payload
        payload_base64 = event.get("payloadBase64")
        if isinstance(payload_base64, str) and payload_base64.strip():
            return _json_loads(base64.b64decode(payload_base64))
        raw_payload = event.get("rawPayload")
        if isinstance(raw_payload, str) and raw_payload.strip():
            return _json_loads(raw_payload)
        return {
            key: value
            for key, value in event.items()
            if key not in {"mqttTopic", "payloadBase64", "rawPayload"}
        }

    def build_mcp_response(
        self,
        message: Mapping[str, Any],
        *,
        active: bool,
        now_ms: int,
    ) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return self.build_json_rpc_error(request_id, -32600, "Invalid JSON-RPC request")
        if request_id is None and method.startswith("notifications/"):
            return None
        if not active:
            return self.build_json_rpc_error(request_id, -32000, "MCP service unavailable")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        }
                    },
                    "serverInfo": {
                        "name": "time",
                        "version": self.server_version,
                    },
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "time.now",
                            "title": "Current time",
                            "description": "Return the current UTC time observed by the virtual time device.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {},
                                "additionalProperties": False,
                            },
                        }
                    ]
                },
            }
        if method == "tools/call":
            params = message.get("params")
            if not isinstance(params, Mapping):
                return self.build_json_rpc_error(request_id, -32602, "Missing params")
            if params.get("name") != "time.now":
                return self.build_json_rpc_error(request_id, -32601, "Unknown tool")
            current_time_iso = utc_iso(now_ms)
            structured = {
                "currentTimeIso": current_time_iso,
                "epochMs": now_ms,
            }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": current_time_iso,
                        }
                    ],
                    "structuredContent": structured,
                    "isError": False,
                },
            }
        return self.build_json_rpc_error(request_id, -32601, "Unknown method")

    @staticmethod
    def build_json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return int(value)


def _region_name_from_env() -> str | None:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or None


def _require_boto3() -> Any:
    if boto3 is None:
        raise RuntimeError("boto3 is required")
    return boto3


def build_iot_client_from_env() -> Any:
    return _require_boto3().client("iot", region_name=_region_name_from_env())


def build_iot_data_client_from_env() -> Any:
    return _require_boto3().client("iot-data", region_name=_region_name_from_env())


def build_runtime_from_env(
    *,
    thing_name: str,
    iot_data_client: Any | None = None,
) -> TimeDeviceRuntime:
    if iot_data_client is None:
        iot_data_client = build_iot_data_client_from_env()
    return TimeDeviceRuntime(
        thing_name=thing_name,
        iot_data_client=iot_data_client,
        active_ttl_ms=_env_int("ACTIVE_TTL_MS", DEFAULT_ACTIVE_TTL_MS),
        server_version=os.getenv("SERVER_VERSION", DEFAULT_SERVER_VERSION),
    )


def discover_time_thing_names(iot_client: Any) -> list[str]:
    thing_names: list[str] = []
    next_token: str | None = None
    while True:
        request: dict[str, Any] = {
            "indexName": "AWS_Things",
            "queryString": TIME_DEVICE_SEARCH_QUERY,
            "maxResults": TIME_DEVICE_SEARCH_PAGE_SIZE,
        }
        if next_token:
            request["nextToken"] = next_token
        response = iot_client.search_index(**request)
        things = response.get("things", [])
        if not isinstance(things, list):
            things = []
        for thing in things:
            if not isinstance(thing, Mapping):
                continue
            thing_name = thing.get("thingName")
            if isinstance(thing_name, str) and thing_name.strip():
                thing_names.append(thing_name.strip())
        token = response.get("nextToken")
        next_token = token.strip() if isinstance(token, str) else None
        if not next_token:
            return thing_names


def handle_scheduled_wake_for_time_devices(
    event: Mapping[str, Any] | None,
    *,
    iot_client: Any,
    iot_data_client: Any,
    active_ttl_ms: int,
    server_version: str,
) -> dict[str, Any]:
    thing_names = discover_time_thing_names(iot_client)
    processed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for thing_name in thing_names:
        runtime = TimeDeviceRuntime(
            thing_name=thing_name,
            iot_data_client=iot_data_client,
            active_ttl_ms=active_ttl_ms,
            server_version=server_version,
        )
        try:
            processed.append(runtime.handle_scheduled_wake(event))
        except Exception as err:
            LOGGER.exception("time scheduled wake failed thingName=%s", thing_name)
            failed.append(
                {
                    "thingName": thing_name,
                    "errorType": type(err).__name__,
                    "error": str(err),
                }
            )
    return {
        "eventType": "schedule",
        "thingCount": len(thing_names),
        "processedCount": len(processed),
        "failedCount": len(failed),
        "processed": processed,
        "failed": failed,
    }


def handle_scheduled_wake_for_time_devices_from_env(
    event: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return handle_scheduled_wake_for_time_devices(
        event,
        iot_client=build_iot_client_from_env(),
        iot_data_client=build_iot_data_client_from_env(),
        active_ttl_ms=_env_int("ACTIVE_TTL_MS", DEFAULT_ACTIVE_TTL_MS),
        server_version=os.getenv("SERVER_VERSION", DEFAULT_SERVER_VERSION),
    )
