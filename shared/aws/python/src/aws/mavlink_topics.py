from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


MAVLINK_TOPIC_NAMESPACE = "txings"
MAVLINK_SERVICE_NAME = "mavlink"
MAVLINK_PROTOCOL_VERSION = "1"
MAVLINK_WIRE_PROTOCOL_VERSION = "2.0"
MAVLINK_DIALECT = "common"
MAVLINK_TRANSPORT = "webrtc-datachannel"
MAVLINK_DATA_CHANNEL_LABEL = "txing.mavlink.v1"
MAVLINK_BINARY_MESSAGE = "mavlink2-unsigned-common-frame"
MAVLINK_TEXT_MESSAGE = "cyberbrick-mavlink-control-json-v1"
MAVLINK_SESSION_AUTHORITY = "daemon"
MAVLINK_ACTIVE_LEASE_TTL_MS = 5_000
MAVLINK_LINK_STATES = frozenset({"starting", "ready", "degraded", "unavailable"})


def _normalize_segment(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    if "/" in text:
        raise ValueError(f"{field_name} must not contain '/'")
    if "+" in text or "#" in text:
        raise ValueError(f"{field_name} must not contain MQTT wildcards")
    return text


def normalize_device_id(device_id: str) -> str:
    return _normalize_segment(device_id, field_name="device_id")

@dataclass(slots=True, frozen=True)
class MavlinkTopics:
    topic_root: str
    descriptor: str
    status: str


@dataclass(slots=True, frozen=True)
class MavlinkTarget:
    system_id: int | None
    component_id: int | None

    def as_payload(self) -> dict[str, int | None]:
        _validate_target(self.system_id, self.component_id)
        return {"systemId": self.system_id, "componentId": self.component_id}


@dataclass(slots=True, frozen=True)
class MavlinkActiveControl:
    session_id: str
    actor: str
    epoch: int
    lease_ttl_ms: int = MAVLINK_ACTIVE_LEASE_TTL_MS

    def as_payload(self) -> dict[str, int | str]:
        session_id = _normalize_segment(self.session_id, field_name="session_id")
        actor = self.actor.strip()
        if not actor:
            raise ValueError("actor must not be empty")
        if self.epoch < 1:
            raise ValueError("epoch must be positive")
        if self.lease_ttl_ms != MAVLINK_ACTIVE_LEASE_TTL_MS:
            raise ValueError(f"lease_ttl_ms must be {MAVLINK_ACTIVE_LEASE_TTL_MS}")
        return {
            "sessionId": session_id,
            "actor": actor,
            "epoch": self.epoch,
            "leaseTtlMs": self.lease_ttl_ms,
        }


@dataclass(slots=True, frozen=True)
class MavlinkError:
    code: str
    message: str

    def as_payload(self) -> dict[str, str]:
        code = self.code.strip()
        message = self.message.strip()
        if not code:
            raise ValueError("error code must not be empty")
        if not message:
            raise ValueError("error message must not be empty")
        return {"code": code, "message": message}


def build_mavlink_topic_root(device_id: str) -> str:
    normalized = normalize_device_id(device_id)
    return f"{MAVLINK_TOPIC_NAMESPACE}/{normalized}/{MAVLINK_SERVICE_NAME}"


def build_mavlink_descriptor_topic(device_id: str) -> str:
    return f"{build_mavlink_topic_root(device_id)}/descriptor"


def build_mavlink_status_topic(device_id: str) -> str:
    return f"{build_mavlink_topic_root(device_id)}/status"


def build_mavlink_topics(device_id: str) -> MavlinkTopics:
    topic_root = build_mavlink_topic_root(device_id)
    return MavlinkTopics(
        topic_root=topic_root,
        descriptor=f"{topic_root}/descriptor",
        status=f"{topic_root}/status",
    )


def parse_mavlink_descriptor_or_status_topic(topic: str) -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) != 4:
        return None
    if parts[0] != MAVLINK_TOPIC_NAMESPACE or parts[2] != MAVLINK_SERVICE_NAME:
        return None
    if parts[3] not in {"descriptor", "status"}:
        return None
    try:
        device_id = normalize_device_id(parts[1])
    except ValueError:
        return None
    return device_id, parts[3]


def build_mavlink_descriptor_payload(
    *,
    device_id: str,
    channel_name: str,
    region: str,
    server_name: str,
    server_version: str,
) -> dict[str, Any]:
    normalized_channel_name = channel_name.strip()
    normalized_region = region.strip()
    normalized_server_name = server_name.strip()
    normalized_server_version = server_version.strip()
    for field_name, value in (
        ("channel_name", normalized_channel_name),
        ("region", normalized_region),
        ("server_name", normalized_server_name),
        ("server_version", normalized_server_version),
    ):
        if not value:
            raise ValueError(f"{field_name} must not be empty")
    topics = build_mavlink_topics(device_id)
    return {
        "serviceId": MAVLINK_SERVICE_NAME,
        "protocolVersion": MAVLINK_PROTOCOL_VERSION,
        "mavlinkWireProtocolVersion": MAVLINK_WIRE_PROTOCOL_VERSION,
        "dialect": MAVLINK_DIALECT,
        "topicRoot": topics.topic_root,
        "descriptorTopic": topics.descriptor,
        "statusTopic": topics.status,
        "transport": MAVLINK_TRANSPORT,
        "channelName": normalized_channel_name,
        "region": normalized_region,
        "dataChannel": {
            "label": MAVLINK_DATA_CHANNEL_LABEL,
            "ordered": True,
            "reliable": True,
            "binaryMessage": MAVLINK_BINARY_MESSAGE,
            "textMessage": MAVLINK_TEXT_MESSAGE,
        },
        "control": {
            "sessionAuthority": MAVLINK_SESSION_AUTHORITY,
            "leaseTtlMs": MAVLINK_ACTIVE_LEASE_TTL_MS,
        },
        "serverInfo": {
            "name": normalized_server_name,
            "version": normalized_server_version,
        },
    }


def build_mavlink_status_payload(
    *,
    available: bool,
    link_state: str,
    heartbeat_fresh: bool,
    target: MavlinkTarget,
    armed: bool,
    mode: str | None,
    connected_peers: int,
    observer_peers: int,
    active_control: MavlinkActiveControl | None,
    errors: Iterable[MavlinkError] = (),
) -> dict[str, Any]:
    normalized_link_state = link_state.strip().lower()
    if normalized_link_state not in MAVLINK_LINK_STATES:
        raise ValueError(f"link_state must be one of {sorted(MAVLINK_LINK_STATES)}")
    if connected_peers < 0 or observer_peers < 0:
        raise ValueError("peer counts must not be negative")
    if observer_peers > connected_peers:
        raise ValueError("observer_peers must not exceed connected_peers")
    normalized_mode = mode.strip() if mode is not None else None
    if normalized_mode == "":
        normalized_mode = None
    return {
        "serviceId": MAVLINK_SERVICE_NAME,
        "available": bool(available),
        "link": {
            "state": normalized_link_state,
            "heartbeatFresh": bool(heartbeat_fresh),
            "mavlinkWireProtocolVersion": MAVLINK_WIRE_PROTOCOL_VERSION,
            "dialect": MAVLINK_DIALECT,
        },
        "target": target.as_payload(),
        "armed": bool(armed),
        "mode": normalized_mode,
        "peers": {
            "connected": int(connected_peers),
            "observers": int(observer_peers),
        },
        "activeControl": active_control.as_payload() if active_control is not None else None,
        "errors": [error.as_payload() for error in errors],
    }


def _validate_target(system_id: int | None, component_id: int | None) -> None:
    if (system_id is None) != (component_id is None):
        raise ValueError("system_id and component_id must both be set or both be None")
    for field_name, value in (("system_id", system_id), ("component_id", component_id)):
        if value is not None and (not isinstance(value, int) or value < 1 or value > 255):
            raise ValueError(f"{field_name} must be an integer from 1 through 255")
