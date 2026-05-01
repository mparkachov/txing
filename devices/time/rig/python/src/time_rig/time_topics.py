from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

TIME_TOPIC_NAMESPACE = "txings"
TIME_SERVICE_NAME = "time"
TIME_MODE_SLEEP = "sleep"
TIME_MODE_ACTIVE = "active"


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


def parse_time_service_topic(topic: str) -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) != 4:
        return None
    if parts[0] != TIME_TOPIC_NAMESPACE or parts[2] != TIME_SERVICE_NAME:
        return None
    if parts[3] not in {"command", "state", "command-result"}:
        return None
    if not parts[1]:
        return None
    return parts[1], parts[3]


@dataclass(slots=True, frozen=True)
class TimeDeviceState:
    thing_name: str
    current_time_iso: str
    mode: str
    active_until_ms: int | None
    last_command_id: str | None
    observed_at_ms: int
    mcp_available: bool

    def to_payload(self) -> dict[str, Any]:
        mode = self.mode.strip()
        if mode not in {TIME_MODE_SLEEP, TIME_MODE_ACTIVE}:
            raise ValueError(f"mode must be {TIME_MODE_SLEEP!r} or {TIME_MODE_ACTIVE!r}")
        return {
            "thingName": _segment(self.thing_name, field_name="thing_name"),
            "currentTimeIso": self.current_time_iso,
            "mode": mode,
            "activeUntilMs": self.active_until_ms,
            "lastCommandId": self.last_command_id,
            "observedAtMs": int(self.observed_at_ms),
            "mcpAvailable": bool(self.mcp_available),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_payload(cls, payload: bytes | str | Mapping[str, Any]) -> TimeDeviceState:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            decoded = json.loads(payload)
        else:
            decoded = payload
        if not isinstance(decoded, Mapping):
            raise ValueError("time state payload must be an object")
        thing_name = decoded.get("thingName")
        current_time_iso = decoded.get("currentTimeIso")
        mode = decoded.get("mode")
        active_until_ms = decoded.get("activeUntilMs")
        last_command_id = decoded.get("lastCommandId")
        observed_at_ms = decoded.get("observedAtMs")
        mcp_available = decoded.get("mcpAvailable")
        if not isinstance(thing_name, str) or not thing_name.strip():
            raise ValueError("thingName must be a non-empty string")
        if not isinstance(current_time_iso, str) or not current_time_iso.strip():
            raise ValueError("currentTimeIso must be a non-empty string")
        if mode not in {TIME_MODE_SLEEP, TIME_MODE_ACTIVE}:
            raise ValueError(f"mode must be {TIME_MODE_SLEEP!r} or {TIME_MODE_ACTIVE!r}")
        if active_until_ms is not None and (
            isinstance(active_until_ms, bool) or not isinstance(active_until_ms, int)
        ):
            raise ValueError("activeUntilMs must be an integer or null")
        if last_command_id is not None and not isinstance(last_command_id, str):
            raise ValueError("lastCommandId must be a string or null")
        if isinstance(observed_at_ms, bool) or not isinstance(observed_at_ms, int):
            raise ValueError("observedAtMs must be an integer")
        if not isinstance(mcp_available, bool):
            raise ValueError("mcpAvailable must be a boolean")
        return cls(
            thing_name=thing_name.strip(),
            current_time_iso=current_time_iso,
            mode=mode,
            active_until_ms=active_until_ms,
            last_command_id=last_command_id,
            observed_at_ms=observed_at_ms,
            mcp_available=mcp_available,
        )
