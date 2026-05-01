from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"
LOCAL_TOPIC_ROOT = "dev/txing/rig/v1/connectivity"

INVENTORY_TOPIC = f"{LOCAL_TOPIC_ROOT}/inventory"
COMMAND_TOPIC_PREFIX = f"{LOCAL_TOPIC_ROOT}/command"
STATE_TOPIC_PREFIX = f"{LOCAL_TOPIC_ROOT}/state"
COMMAND_RESULT_TOPIC_PREFIX = f"{LOCAL_TOPIC_ROOT}/command-result"
HEARTBEAT_TOPIC_PREFIX = f"{LOCAL_TOPIC_ROOT}/heartbeat"

TRANSPORT_BLE_GATT = "ble-gatt"
TRANSPORT_MATTER = "matter"

SLEEP_MODEL_BLE_RENDEZVOUS = "ble-rendezvous"
SLEEP_MODEL_MATTER_ICD = "matter-icd"
SLEEP_MODEL_ALWAYS_ON = "always-on"

PRESENCE_ONLINE = "online"
PRESENCE_OFFLINE = "offline"
PRESENCE_UNKNOWN = "unknown"

CONTROL_IMMEDIATE = "immediate"
CONTROL_EVENTUAL = "eventual"
CONTROL_UNAVAILABLE = "unavailable"

COMMAND_PENDING = "pending"
COMMAND_ACCEPTED = "accepted"
COMMAND_SUCCEEDED = "succeeded"
COMMAND_FAILED = "failed"

VALID_TRANSPORTS = {
    TRANSPORT_BLE_GATT,
    TRANSPORT_MATTER,
}
VALID_SLEEP_MODELS = {
    SLEEP_MODEL_BLE_RENDEZVOUS,
    SLEEP_MODEL_MATTER_ICD,
    SLEEP_MODEL_ALWAYS_ON,
}
VALID_PRESENCE = {
    PRESENCE_ONLINE,
    PRESENCE_OFFLINE,
    PRESENCE_UNKNOWN,
}
VALID_CONTROL_AVAILABILITY = {
    CONTROL_IMMEDIATE,
    CONTROL_EVENTUAL,
    CONTROL_UNAVAILABLE,
}
VALID_COMMAND_STATUS = {
    COMMAND_PENDING,
    COMMAND_ACCEPTED,
    COMMAND_SUCCEEDED,
    COMMAND_FAILED,
}


class ConnectivityProtocolError(ValueError):
    pass


def _topic_segment(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ConnectivityProtocolError(f"{field_name} must not be empty")
    if "/" in text or "+" in text or "#" in text:
        raise ConnectivityProtocolError(f"{field_name} must be a literal MQTT segment")
    return text


def build_command_topic(thing_name: str) -> str:
    return f"{COMMAND_TOPIC_PREFIX}/{_topic_segment(thing_name, field_name='thing_name')}"


def build_state_topic(thing_name: str) -> str:
    return f"{STATE_TOPIC_PREFIX}/{_topic_segment(thing_name, field_name='thing_name')}"


def build_command_result_topic(thing_name: str) -> str:
    return f"{COMMAND_RESULT_TOPIC_PREFIX}/{_topic_segment(thing_name, field_name='thing_name')}"


def build_heartbeat_topic(adapter_id: str) -> str:
    return f"{HEARTBEAT_TOPIC_PREFIX}/{_topic_segment(adapter_id, field_name='adapter_id')}"


def parse_suffixed_topic(topic: str, prefix: str) -> str | None:
    topic_prefix = f"{prefix}/"
    if not topic.startswith(topic_prefix):
        return None
    suffix = topic[len(topic_prefix) :]
    if not suffix or "/" in suffix:
        return None
    return suffix


def parse_command_topic(topic: str) -> str | None:
    return parse_suffixed_topic(topic, COMMAND_TOPIC_PREFIX)


def parse_state_topic(topic: str) -> str | None:
    return parse_suffixed_topic(topic, STATE_TOPIC_PREFIX)


def parse_command_result_topic(topic: str) -> str | None:
    return parse_suffixed_topic(topic, COMMAND_RESULT_TOPIC_PREFIX)


def parse_heartbeat_topic(topic: str) -> str | None:
    return parse_suffixed_topic(topic, HEARTBEAT_TOPIC_PREFIX)


def _require_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConnectivityProtocolError(f"{field_name} must be an object")
    return value


def _optional_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConnectivityProtocolError(f"{field_name} must be an object")
    return dict(value)


def _required_str(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ConnectivityProtocolError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_str(payload: Mapping[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConnectivityProtocolError(f"{field_name} must be a string")
    text = value.strip()
    return text or None


def _optional_bool(payload: Mapping[str, Any], field_name: str) -> bool | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ConnectivityProtocolError(f"{field_name} must be a boolean")
    return value


def _optional_int(payload: Mapping[str, Any], field_name: str) -> int | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConnectivityProtocolError(f"{field_name} must be an integer")
    return value


def _required_int(payload: Mapping[str, Any], field_name: str) -> int:
    value = _optional_int(payload, field_name)
    if value is None:
        raise ConnectivityProtocolError(f"{field_name} must be an integer")
    return value


def _validate_choice(value: str, choices: set[str], *, field_name: str) -> str:
    if value not in choices:
        raise ConnectivityProtocolError(
            f"{field_name} must be one of {', '.join(sorted(choices))}"
        )
    return value


def _validate_schema(payload: Mapping[str, Any]) -> None:
    schema_version = payload.get("schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise ConnectivityProtocolError(
            f"schemaVersion must be {SCHEMA_VERSION!r}, got {schema_version!r}"
        )


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _json_loads(payload: bytes | str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as err:
            raise ConnectivityProtocolError("payload must be UTF-8 JSON") from err
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as err:
        raise ConnectivityProtocolError("payload must be valid JSON") from err
    return _require_mapping(decoded, field_name="payload")


@dataclass(slots=True, frozen=True)
class ConnectivityDeviceConfig:
    thing_name: str
    transport: str = TRANSPORT_BLE_GATT
    native_identity: dict[str, Any] = field(default_factory=dict)
    sleep_model: str = SLEEP_MODEL_BLE_RENDEZVOUS

    def to_payload(self) -> dict[str, Any]:
        return {
            "thingName": _topic_segment(self.thing_name, field_name="thing_name"),
            "transport": _validate_choice(
                self.transport,
                VALID_TRANSPORTS,
                field_name="transport",
            ),
            "nativeIdentity": dict(self.native_identity),
            "sleepModel": _validate_choice(
                self.sleep_model,
                VALID_SLEEP_MODELS,
                field_name="sleepModel",
            ),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ConnectivityDeviceConfig:
        native_identity = _optional_mapping(
            payload.get("nativeIdentity"),
            field_name="nativeIdentity",
        )
        return cls(
            thing_name=_required_str(payload, "thingName"),
            transport=_validate_choice(
                _required_str(payload, "transport"),
                VALID_TRANSPORTS,
                field_name="transport",
            ),
            native_identity=native_identity,
            sleep_model=_validate_choice(
                _required_str(payload, "sleepModel"),
                VALID_SLEEP_MODELS,
                field_name="sleepModel",
            ),
        )


@dataclass(slots=True, frozen=True)
class ConnectivityInventory:
    adapter_id: str
    devices: tuple[ConnectivityDeviceConfig, ...]
    seq: int
    issued_at_ms: int
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "adapterId": _topic_segment(self.adapter_id, field_name="adapter_id"),
            "seq": int(self.seq),
            "issuedAtMs": int(self.issued_at_ms),
            "devices": [device.to_payload() for device in self.devices],
        }

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> ConnectivityInventory:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        raw_devices = decoded.get("devices")
        if not isinstance(raw_devices, list):
            raise ConnectivityProtocolError("devices must be an array")
        return cls(
            adapter_id=_required_str(decoded, "adapterId"),
            seq=_required_int(decoded, "seq"),
            issued_at_ms=_required_int(decoded, "issuedAtMs"),
            devices=tuple(
                ConnectivityDeviceConfig.from_payload(
                    _require_mapping(item, field_name="devices[]")
                )
                for item in raw_devices
            ),
        )


@dataclass(slots=True, frozen=True)
class ConnectivityCommand:
    command_id: str
    thing_name: str
    power: bool
    reason: str
    issued_at_ms: int
    deadline_ms: int | None = None
    seq: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "commandId": _required_str({"commandId": self.command_id}, "commandId"),
            "thingName": _topic_segment(self.thing_name, field_name="thing_name"),
            "seq": int(self.seq),
            "target": {"power": bool(self.power)},
            "reason": str(self.reason),
            "issuedAtMs": int(self.issued_at_ms),
        }
        if self.deadline_ms is not None:
            payload["deadlineMs"] = int(self.deadline_ms)
        return payload

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> ConnectivityCommand:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        target = _require_mapping(decoded.get("target"), field_name="target")
        power = target.get("power")
        if not isinstance(power, bool):
            raise ConnectivityProtocolError("target.power must be a boolean")
        return cls(
            command_id=_required_str(decoded, "commandId"),
            thing_name=_required_str(decoded, "thingName"),
            power=power,
            reason=_required_str(decoded, "reason"),
            issued_at_ms=_required_int(decoded, "issuedAtMs"),
            deadline_ms=_optional_int(decoded, "deadlineMs"),
            seq=_optional_int(decoded, "seq") or 0,
        )


@dataclass(slots=True, frozen=True)
class ConnectivityState:
    adapter_id: str
    thing_name: str
    transport: str
    native_identity: dict[str, Any]
    presence: str
    control_availability: str
    power: bool | None
    sleep_model: str
    battery_mv: int | None
    observed_at_ms: int
    seq: int = 0
    schema_version: str = SCHEMA_VERSION

    @property
    def reachable(self) -> bool:
        return (
            self.presence == PRESENCE_ONLINE
            and self.control_availability != CONTROL_UNAVAILABLE
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "adapterId": _topic_segment(self.adapter_id, field_name="adapter_id"),
            "thingName": _topic_segment(self.thing_name, field_name="thing_name"),
            "transport": _validate_choice(
                self.transport,
                VALID_TRANSPORTS,
                field_name="transport",
            ),
            "nativeIdentity": dict(self.native_identity),
            "presence": _validate_choice(
                self.presence,
                VALID_PRESENCE,
                field_name="presence",
            ),
            "controlAvailability": _validate_choice(
                self.control_availability,
                VALID_CONTROL_AVAILABILITY,
                field_name="controlAvailability",
            ),
            "power": self.power,
            "sleepModel": _validate_choice(
                self.sleep_model,
                VALID_SLEEP_MODELS,
                field_name="sleepModel",
            ),
            "batteryMv": self.battery_mv,
            "observedAtMs": int(self.observed_at_ms),
            "seq": int(self.seq),
        }
        return payload

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> ConnectivityState:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        return cls(
            adapter_id=_required_str(decoded, "adapterId"),
            thing_name=_required_str(decoded, "thingName"),
            transport=_validate_choice(
                _required_str(decoded, "transport"),
                VALID_TRANSPORTS,
                field_name="transport",
            ),
            native_identity=_optional_mapping(
                decoded.get("nativeIdentity"),
                field_name="nativeIdentity",
            ),
            presence=_validate_choice(
                _required_str(decoded, "presence"),
                VALID_PRESENCE,
                field_name="presence",
            ),
            control_availability=_validate_choice(
                _required_str(decoded, "controlAvailability"),
                VALID_CONTROL_AVAILABILITY,
                field_name="controlAvailability",
            ),
            power=_optional_bool(decoded, "power"),
            sleep_model=_validate_choice(
                _required_str(decoded, "sleepModel"),
                VALID_SLEEP_MODELS,
                field_name="sleepModel",
            ),
            battery_mv=_optional_int(decoded, "batteryMv"),
            observed_at_ms=_required_int(decoded, "observedAtMs"),
            seq=_optional_int(decoded, "seq") or 0,
        )


@dataclass(slots=True, frozen=True)
class ConnectivityCommandResult:
    adapter_id: str
    command_id: str
    thing_name: str
    status: str
    message: str | None
    observed_at_ms: int
    seq: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "adapterId": _topic_segment(self.adapter_id, field_name="adapter_id"),
            "commandId": _required_str({"commandId": self.command_id}, "commandId"),
            "thingName": _topic_segment(self.thing_name, field_name="thing_name"),
            "status": _validate_choice(
                self.status,
                VALID_COMMAND_STATUS,
                field_name="status",
            ),
            "message": self.message,
            "observedAtMs": int(self.observed_at_ms),
            "seq": int(self.seq),
        }

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(
        cls,
        payload: bytes | str | Mapping[str, Any],
    ) -> ConnectivityCommandResult:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        return cls(
            adapter_id=_required_str(decoded, "adapterId"),
            command_id=_required_str(decoded, "commandId"),
            thing_name=_required_str(decoded, "thingName"),
            status=_validate_choice(
                _required_str(decoded, "status"),
                VALID_COMMAND_STATUS,
                field_name="status",
            ),
            message=_optional_str(decoded, "message"),
            observed_at_ms=_required_int(decoded, "observedAtMs"),
            seq=_optional_int(decoded, "seq") or 0,
        )


@dataclass(slots=True, frozen=True)
class ConnectivityHeartbeat:
    adapter_id: str
    status: str
    active_thing_name: str | None
    observed_at_ms: int
    seq: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "adapterId": _topic_segment(self.adapter_id, field_name="adapter_id"),
            "status": _required_str({"status": self.status}, "status"),
            "activeThingName": self.active_thing_name,
            "observedAtMs": int(self.observed_at_ms),
            "seq": int(self.seq),
        }

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> ConnectivityHeartbeat:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        return cls(
            adapter_id=_required_str(decoded, "adapterId"),
            status=_required_str(decoded, "status"),
            active_thing_name=_optional_str(decoded, "activeThingName"),
            observed_at_ms=_required_int(decoded, "observedAtMs"),
            seq=_optional_int(decoded, "seq") or 0,
        )
