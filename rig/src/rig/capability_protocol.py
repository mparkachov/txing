from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = "2.0"
LOCAL_TOPIC_ROOT = "dev/txing/rig/v2"

INVENTORY_TOPIC = f"{LOCAL_TOPIC_ROOT}/inventory"
CAPABILITY_STATE_TOPIC_PREFIX = f"{LOCAL_TOPIC_ROOT}/capability/state"
CAPABILITY_COMMAND_TOPIC_PREFIX = f"{LOCAL_TOPIC_ROOT}/capability/command"
CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX = f"{LOCAL_TOPIC_ROOT}/capability/command-result"
CAPABILITY_HEARTBEAT_TOPIC_PREFIX = f"{LOCAL_TOPIC_ROOT}/capability/heartbeat"

COMMAND_PENDING = "pending"
COMMAND_ACCEPTED = "accepted"
COMMAND_SUCCEEDED = "succeeded"
COMMAND_FAILED = "failed"

HEARTBEAT_RUNNING = "running"

VALID_COMMAND_STATUS = {
    COMMAND_PENDING,
    COMMAND_ACCEPTED,
    COMMAND_SUCCEEDED,
    COMMAND_FAILED,
}

VALID_METRIC_DATATYPES = {
    "Boolean",
    "Int32",
    "Int64",
    "UInt32",
    "UInt64",
    "Float",
    "Double",
    "String",
}


class CapabilityProtocolError(ValueError):
    pass


def _topic_segment(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise CapabilityProtocolError(f"{field_name} must not be empty")
    if "/" in text or "+" in text or "#" in text:
        raise CapabilityProtocolError(f"{field_name} must be a literal MQTT segment")
    return text


def build_capability_state_topic(thing_name: str, adapter_id: str) -> str:
    return "/".join(
        (
            CAPABILITY_STATE_TOPIC_PREFIX,
            _topic_segment(thing_name, field_name="thing_name"),
            _topic_segment(adapter_id, field_name="adapter_id"),
        )
    )


def build_capability_command_topic(thing_name: str) -> str:
    return f"{CAPABILITY_COMMAND_TOPIC_PREFIX}/{_topic_segment(thing_name, field_name='thing_name')}"


def build_capability_command_result_topic(thing_name: str, adapter_id: str) -> str:
    return "/".join(
        (
            CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX,
            _topic_segment(thing_name, field_name="thing_name"),
            _topic_segment(adapter_id, field_name="adapter_id"),
        )
    )


def build_capability_heartbeat_topic(adapter_id: str) -> str:
    return f"{CAPABILITY_HEARTBEAT_TOPIC_PREFIX}/{_topic_segment(adapter_id, field_name='adapter_id')}"


def parse_capability_state_topic(topic: str) -> tuple[str, str] | None:
    return _parse_two_segment_suffix(topic, CAPABILITY_STATE_TOPIC_PREFIX)


def parse_capability_command_topic(topic: str) -> str | None:
    prefix = f"{CAPABILITY_COMMAND_TOPIC_PREFIX}/"
    if not topic.startswith(prefix):
        return None
    suffix = topic[len(prefix) :]
    if not suffix or "/" in suffix:
        return None
    return suffix


def parse_capability_command_result_topic(topic: str) -> tuple[str, str] | None:
    return _parse_two_segment_suffix(topic, CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX)


def parse_capability_heartbeat_topic(topic: str) -> str | None:
    prefix = f"{CAPABILITY_HEARTBEAT_TOPIC_PREFIX}/"
    if not topic.startswith(prefix):
        return None
    suffix = topic[len(prefix) :]
    if not suffix or "/" in suffix:
        return None
    return suffix


def _parse_two_segment_suffix(topic: str, prefix: str) -> tuple[str, str] | None:
    topic_prefix = f"{prefix}/"
    if not topic.startswith(topic_prefix):
        return None
    suffix = topic[len(topic_prefix) :]
    parts = suffix.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _require_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CapabilityProtocolError(f"{field_name} must be an object")
    return value


def _required_str(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise CapabilityProtocolError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_str(payload: Mapping[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CapabilityProtocolError(f"{field_name} must be a string")
    text = value.strip()
    return text or None


def _required_int(payload: Mapping[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapabilityProtocolError(f"{field_name} must be an integer")
    return value


def _optional_int(payload: Mapping[str, Any], field_name: str) -> int | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapabilityProtocolError(f"{field_name} must be an integer")
    return value


def _required_redcon(payload: Mapping[str, Any], field_name: str) -> int:
    value = _required_int(payload, field_name)
    if value < 1 or value > 4:
        raise CapabilityProtocolError(f"{field_name} must be a REDCON level 1 through 4")
    return value


def _optional_redcon(payload: Mapping[str, Any], field_name: str) -> int | None:
    value = _optional_int(payload, field_name)
    if value is None:
        return None
    if value < 1 or value > 4:
        raise CapabilityProtocolError(f"{field_name} must be a REDCON level 1 through 4")
    return value


def _text_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CapabilityProtocolError(f"{field_name} must be an array")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CapabilityProtocolError(f"{field_name} entries must be non-empty strings")
        text = item.strip()
        if text in seen:
            raise CapabilityProtocolError(f"{field_name} contains duplicate value {text!r}")
        seen.add(text)
        result.append(text)
    return tuple(result)


def _redcon_level_list(value: Any, *, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise CapabilityProtocolError(f"{field_name} must be an array")
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        if isinstance(item, str) and item.isdigit():
            item = int(item)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1 or item > 4:
            raise CapabilityProtocolError(f"{field_name} entries must be REDCON levels 1 through 4")
        if item in seen:
            raise CapabilityProtocolError(f"{field_name} contains duplicate REDCON level {item}")
        seen.add(item)
        result.append(item)
    return tuple(result)


def _capability_bool_map(value: Any, *, field_name: str) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        raise CapabilityProtocolError(f"{field_name} must be an object")
    result: dict[str, bool] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise CapabilityProtocolError(f"{field_name} keys must be non-empty strings")
        if not isinstance(item, bool):
            raise CapabilityProtocolError(f"{field_name}.{key} must be a boolean")
        result[key.strip()] = item
    return result


def _redcon_rules(value: Any, *, field_name: str) -> dict[int, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise CapabilityProtocolError(f"{field_name} must be an object")
    result: dict[int, tuple[str, ...]] = {}
    for key, item in value.items():
        try:
            level = int(key)
        except (TypeError, ValueError) as err:
            raise CapabilityProtocolError(f"{field_name} keys must be REDCON levels") from err
        if level < 1 or level > 4:
            raise CapabilityProtocolError(f"{field_name} keys must be REDCON levels 1 through 4")
        result[level] = _text_list(item, field_name=f"{field_name}.{key}")
    return result


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _json_loads(payload: bytes | str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as err:
            raise CapabilityProtocolError("payload must be UTF-8 JSON") from err
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as err:
        raise CapabilityProtocolError("payload must be valid JSON") from err
    return _require_mapping(decoded, field_name="payload")


def _validate_schema(payload: Mapping[str, Any]) -> None:
    schema_version = payload.get("schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise CapabilityProtocolError(
            f"schemaVersion must be {SCHEMA_VERSION!r}, got {schema_version!r}"
        )


def _validate_choice(value: str, choices: set[str], *, field_name: str) -> str:
    if value not in choices:
        raise CapabilityProtocolError(
            f"{field_name} must be one of {', '.join(sorted(choices))}"
        )
    return value


@dataclass(slots=True, frozen=True)
class SparkplugMetricValue:
    datatype: str
    value: Any

    def to_payload(self) -> dict[str, Any]:
        datatype = _validate_choice(
            self.datatype,
            VALID_METRIC_DATATYPES,
            field_name="datatype",
        )
        value = self.value
        if datatype == "Boolean" and not isinstance(value, bool):
            raise CapabilityProtocolError("Boolean metric value must be a boolean")
        if datatype in {"Int32", "Int64", "UInt32", "UInt64"} and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise CapabilityProtocolError(f"{datatype} metric value must be an integer")
        if datatype in {"Float", "Double"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CapabilityProtocolError(f"{datatype} metric value must be a number")
            if not math.isfinite(float(value)):
                raise CapabilityProtocolError(f"{datatype} metric value must be finite")
        if datatype == "String" and not isinstance(value, str):
            raise CapabilityProtocolError("String metric value must be a string")
        return {
            "datatype": datatype,
            "value": value,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SparkplugMetricValue:
        metric = cls(
            datatype=_required_str(payload, "datatype"),
            value=payload.get("value"),
        )
        metric.to_payload()
        return metric


@dataclass(slots=True, frozen=True)
class CapabilityWeatherMeasurements:
    measured_temperature: float | None = None
    measured_pressure: float | None = None
    measured_humidity: float | None = None


@dataclass(slots=True, frozen=True)
class CapabilityInventoryDevice:
    thing_name: str
    thing_type: str
    capabilities: tuple[str, ...]
    redcon_command_levels: tuple[int, ...]
    redcon_rules: dict[int, tuple[str, ...]]

    def to_payload(self) -> dict[str, Any]:
        return {
            "thingName": _topic_segment(self.thing_name, field_name="thing_name"),
            "thingType": _topic_segment(self.thing_type, field_name="thing_type"),
            "capabilities": list(self.capabilities),
            "redconCommandLevels": list(self.redcon_command_levels),
            "redconRules": {str(level): list(capabilities) for level, capabilities in sorted(self.redcon_rules.items())},
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CapabilityInventoryDevice:
        return cls(
            thing_name=_required_str(payload, "thingName"),
            thing_type=_required_str(payload, "thingType"),
            capabilities=_text_list(payload.get("capabilities"), field_name="capabilities"),
            redcon_command_levels=_redcon_level_list(
                payload.get("redconCommandLevels"),
                field_name="redconCommandLevels",
            ),
            redcon_rules=_redcon_rules(payload.get("redconRules"), field_name="redconRules"),
        )


@dataclass(slots=True, frozen=True)
class CapabilityInventory:
    manager_id: str
    devices: tuple[CapabilityInventoryDevice, ...]
    seq: int
    issued_at_ms: int
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "managerId": _topic_segment(self.manager_id, field_name="manager_id"),
            "seq": int(self.seq),
            "issuedAtMs": int(self.issued_at_ms),
            "devices": [device.to_payload() for device in self.devices],
        }

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> CapabilityInventory:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        raw_devices = decoded.get("devices")
        if not isinstance(raw_devices, list):
            raise CapabilityProtocolError("devices must be an array")
        return cls(
            manager_id=_required_str(decoded, "managerId"),
            seq=_required_int(decoded, "seq"),
            issued_at_ms=_required_int(decoded, "issuedAtMs"),
            devices=tuple(
                CapabilityInventoryDevice.from_payload(
                    _require_mapping(item, field_name="devices[]")
                )
                for item in raw_devices
            ),
        )


@dataclass(slots=True, frozen=True)
class CapabilityState:
    adapter_id: str
    thing_name: str
    capabilities: dict[str, bool]
    metrics: dict[str, SparkplugMetricValue] = field(default_factory=dict)
    observed_at_ms: int = 0
    seq: int = 0
    schema_version: str = SCHEMA_VERSION

    @property
    def reachable(self) -> bool:
        return bool(self.capabilities.get("sparkplug"))

    @property
    def power(self) -> bool:
        return bool(
            self.capabilities.get("power")
            or self.capabilities.get("weather")
            or self.capabilities.get("time")
        )

    @property
    def battery_mv(self) -> int | None:
        metric = self.metrics.get("batteryMv")
        if metric is None or metric.datatype not in {"Int32", "Int64", "UInt32", "UInt64"}:
            return None
        return int(metric.value)

    @property
    def weather(self) -> CapabilityWeatherMeasurements | None:
        names = ("measuredTemperature", "measuredPressure", "measuredHumidity")
        if not any(name in self.metrics for name in names):
            return None
        return CapabilityWeatherMeasurements(
            measured_temperature=_metric_float(self.metrics.get("measuredTemperature")),
            measured_pressure=_metric_float(self.metrics.get("measuredPressure")),
            measured_humidity=_metric_float(self.metrics.get("measuredHumidity")),
        )

    @property
    def native_identity(self) -> dict[str, Any]:
        identity: dict[str, Any] = {"bleLocalName": self.thing_name}
        for name in (
            "currentTimeIso",
            "activeUntilMs",
            "lastCommandId",
            "mcpAvailable",
            "bleConnected",
            "bleLocalName",
            "bleAddress",
        ):
            metric = self.metrics.get(name)
            if metric is not None:
                identity[name] = metric.value
        return identity

    @property
    def transport(self) -> str:
        if "ble" in self.capabilities:
            return "ble-gatt"
        return "matter"

    @property
    def sleep_model(self) -> str:
        if "ble" in self.capabilities:
            return "ble-connected-idle"
        return "matter-icd"

    def to_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "adapterId": _topic_segment(self.adapter_id, field_name="adapter_id"),
            "thingName": _topic_segment(self.thing_name, field_name="thing_name"),
            "capabilities": dict(self.capabilities),
            "metrics": {
                name: metric.to_payload()
                for name, metric in sorted(self.metrics.items())
            },
            "observedAtMs": int(self.observed_at_ms),
            "seq": int(self.seq),
        }

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> CapabilityState:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        raw_metrics = decoded.get("metrics")
        if raw_metrics is None:
            raw_metrics = {}
        if not isinstance(raw_metrics, Mapping):
            raise CapabilityProtocolError("metrics must be an object")
        metrics: dict[str, SparkplugMetricValue] = {}
        for name, raw_metric in raw_metrics.items():
            if not isinstance(name, str) or not name.strip():
                raise CapabilityProtocolError("metrics keys must be non-empty strings")
            metrics[name.strip()] = SparkplugMetricValue.from_payload(
                _require_mapping(raw_metric, field_name=f"metrics.{name}")
            )
        return cls(
            adapter_id=_required_str(decoded, "adapterId"),
            thing_name=_required_str(decoded, "thingName"),
            capabilities=_capability_bool_map(decoded.get("capabilities"), field_name="capabilities"),
            metrics=metrics,
            observed_at_ms=_required_int(decoded, "observedAtMs"),
            seq=_optional_int(decoded, "seq") or 0,
        )


def _metric_float(metric: SparkplugMetricValue | None) -> float | None:
    if metric is None:
        return None
    if metric.datatype not in {"Float", "Double"}:
        return None
    return float(metric.value)


@dataclass(slots=True, frozen=True)
class CapabilityCommand:
    command_id: str
    thing_name: str
    redcon: int
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
            "target": {"redcon": _required_redcon({"redcon": self.redcon}, "redcon")},
            "reason": str(self.reason),
            "issuedAtMs": int(self.issued_at_ms),
        }
        if self.deadline_ms is not None:
            payload["deadlineMs"] = int(self.deadline_ms)
        return payload

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> CapabilityCommand:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        target = _require_mapping(decoded.get("target"), field_name="target")
        return cls(
            command_id=_required_str(decoded, "commandId"),
            thing_name=_required_str(decoded, "thingName"),
            redcon=_required_redcon(target, "redcon"),
            reason=_required_str(decoded, "reason"),
            issued_at_ms=_required_int(decoded, "issuedAtMs"),
            deadline_ms=_optional_int(decoded, "deadlineMs"),
            seq=_optional_int(decoded, "seq") or 0,
        )


@dataclass(slots=True, frozen=True)
class CapabilityCommandResult:
    adapter_id: str
    command_id: str
    thing_name: str
    status: str
    redcon: int | None
    message: str | None
    observed_at_ms: int
    seq: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "adapterId": _topic_segment(self.adapter_id, field_name="adapter_id"),
            "commandId": _required_str({"commandId": self.command_id}, "commandId"),
            "thingName": _topic_segment(self.thing_name, field_name="thing_name"),
            "status": _validate_choice(self.status, VALID_COMMAND_STATUS, field_name="status"),
            "target": {},
            "message": self.message,
            "observedAtMs": int(self.observed_at_ms),
            "seq": int(self.seq),
        }
        if self.redcon is not None:
            payload["target"] = {"redcon": _required_redcon({"redcon": self.redcon}, "redcon")}
        return payload

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> CapabilityCommandResult:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        target = _require_mapping(decoded.get("target", {}), field_name="target")
        return cls(
            adapter_id=_required_str(decoded, "adapterId"),
            command_id=_required_str(decoded, "commandId"),
            thing_name=_required_str(decoded, "thingName"),
            status=_validate_choice(
                _required_str(decoded, "status"),
                VALID_COMMAND_STATUS,
                field_name="status",
            ),
            redcon=_optional_redcon(target, "redcon"),
            message=_optional_str(decoded, "message"),
            observed_at_ms=_required_int(decoded, "observedAtMs"),
            seq=_optional_int(decoded, "seq") or 0,
        )


@dataclass(slots=True, frozen=True)
class CapabilityHeartbeat:
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
            "status": str(self.status),
            "activeThingName": self.active_thing_name,
            "observedAtMs": int(self.observed_at_ms),
            "seq": int(self.seq),
        }

    def to_json(self) -> str:
        return _json_dumps(self.to_payload())

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> CapabilityHeartbeat:
        decoded = _json_loads(payload)
        _validate_schema(decoded)
        return cls(
            adapter_id=_required_str(decoded, "adapterId"),
            status=_required_str(decoded, "status"),
            active_thing_name=_optional_str(decoded, "activeThingName"),
            observed_at_ms=_required_int(decoded, "observedAtMs"),
            seq=_optional_int(decoded, "seq") or 0,
        )
