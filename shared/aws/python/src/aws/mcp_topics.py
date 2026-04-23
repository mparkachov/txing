from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MCP_TOPIC_NAMESPACE = "txings"
MCP_SERVICE_NAME = "mcp"
MCP_TRANSPORT = "mqtt-jsonrpc"
MCP_WEBRTC_DATA_CHANNEL_TRANSPORT = "webrtc-datachannel"
MCP_WEBRTC_DATA_CHANNEL_LABEL = "txing.mcp.v1"
MCP_WEBRTC_SIGNALING = "aws-kvs"
MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_DEFAULT_LEASE_TTL_MS = 5000


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


def normalize_session_id(session_id: str) -> str:
    return _normalize_segment(session_id, field_name="session_id")


@dataclass(slots=True, frozen=True)
class McpTopics:
    topic_root: str
    descriptor: str
    status: str
    session_c2s_pattern: str
    session_s2c_pattern: str
    session_c2s_subscription: str


def build_mcp_topic_root(device_id: str) -> str:
    normalized = normalize_device_id(device_id)
    return f"{MCP_TOPIC_NAMESPACE}/{normalized}/{MCP_SERVICE_NAME}"


def build_mcp_descriptor_topic(device_id: str) -> str:
    return f"{build_mcp_topic_root(device_id)}/descriptor"


def build_mcp_status_topic(device_id: str) -> str:
    return f"{build_mcp_topic_root(device_id)}/status"


def build_mcp_session_c2s_topic(device_id: str, session_id: str) -> str:
    normalized_session_id = normalize_session_id(session_id)
    return f"{build_mcp_topic_root(device_id)}/session/{normalized_session_id}/c2s"


def build_mcp_session_s2c_topic(device_id: str, session_id: str) -> str:
    normalized_session_id = normalize_session_id(session_id)
    return f"{build_mcp_topic_root(device_id)}/session/{normalized_session_id}/s2c"


def build_mcp_session_c2s_subscription(device_id: str) -> str:
    return f"{build_mcp_topic_root(device_id)}/session/+/c2s"


def build_mcp_topics(device_id: str) -> McpTopics:
    topic_root = build_mcp_topic_root(device_id)
    return McpTopics(
        topic_root=topic_root,
        descriptor=f"{topic_root}/descriptor",
        status=f"{topic_root}/status",
        session_c2s_pattern=f"{topic_root}/session/{{sessionId}}/c2s",
        session_s2c_pattern=f"{topic_root}/session/{{sessionId}}/s2c",
        session_c2s_subscription=f"{topic_root}/session/+/c2s",
    )


def parse_mcp_descriptor_or_status_topic(topic: str) -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) != 4:
        return None
    if parts[0] != MCP_TOPIC_NAMESPACE or parts[2] != MCP_SERVICE_NAME:
        return None
    kind = parts[3]
    if kind not in {"descriptor", "status"}:
        return None
    device_id = parts[1]
    if not device_id:
        return None
    return device_id, kind


def parse_mcp_session_c2s_topic(topic: str, *, device_id: str) -> str | None:
    root = build_mcp_topic_root(device_id)
    prefix = f"{root}/session/"
    suffix = "/c2s"
    if not topic.startswith(prefix) or not topic.endswith(suffix):
        return None
    raw_session_id = topic[len(prefix) : -len(suffix)]
    if not raw_session_id:
        return None
    if "/" in raw_session_id:
        return None
    return raw_session_id


def parse_mcp_session_s2c_topic(topic: str, *, device_id: str) -> str | None:
    root = build_mcp_topic_root(device_id)
    prefix = f"{root}/session/"
    suffix = "/s2c"
    if not topic.startswith(prefix) or not topic.endswith(suffix):
        return None
    raw_session_id = topic[len(prefix) : -len(suffix)]
    if not raw_session_id:
        return None
    if "/" in raw_session_id:
        return None
    return raw_session_id


def build_mcp_descriptor_payload(
    *,
    device_id: str,
    server_version: str,
    lease_required: bool = True,
    lease_ttl_ms: int = MCP_DEFAULT_LEASE_TTL_MS,
    mcp_protocol_version: str = MCP_PROTOCOL_VERSION,
    transport: str = MCP_TRANSPORT,
    webrtc_channel_name: str | None = None,
    webrtc_region: str | None = None,
    webrtc_data_channel_label: str = MCP_WEBRTC_DATA_CHANNEL_LABEL,
) -> dict[str, Any]:
    if lease_ttl_ms <= 0:
        raise ValueError("lease_ttl_ms must be positive")
    topics = build_mcp_topics(device_id)
    session_topic_pattern = {
        "clientToServer": topics.session_c2s_pattern,
        "serverToClient": topics.session_s2c_pattern,
    }
    transports: list[dict[str, Any]] = []
    normalized_webrtc_channel_name = (webrtc_channel_name or "").strip()
    normalized_webrtc_region = (webrtc_region or "").strip()
    if normalized_webrtc_channel_name and normalized_webrtc_region:
        transports.append(
            {
                "type": MCP_WEBRTC_DATA_CHANNEL_TRANSPORT,
                "priority": 10,
                "signaling": MCP_WEBRTC_SIGNALING,
                "channelName": normalized_webrtc_channel_name,
                "region": normalized_webrtc_region,
                "label": webrtc_data_channel_label,
            }
        )
    transports.append(
        {
            "type": MCP_TRANSPORT,
            "priority": 100,
            "topicRoot": topics.topic_root,
            "sessionTopicPattern": session_topic_pattern,
        }
    )
    return {
        "serviceId": MCP_SERVICE_NAME,
        "serverInfo": {
            "name": MCP_SERVICE_NAME,
            "version": server_version,
        },
        "transport": transport,
        "mcpProtocolVersion": mcp_protocol_version,
        "topicRoot": topics.topic_root,
        "descriptorTopic": topics.descriptor,
        "sessionTopicPattern": session_topic_pattern,
        "transports": transports,
        "leaseRequired": bool(lease_required),
        "leaseTtlMs": int(lease_ttl_ms),
        "serverVersion": server_version,
    }


def build_mcp_status_payload(
    *,
    available: bool,
    lease_owner_session_id: str | None = None,
    lease_expires_at_ms: int | None = None,
    updated_at_ms: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "serviceId": MCP_SERVICE_NAME,
        "available": bool(available),
    }
    if lease_owner_session_id is not None:
        payload["leaseOwnerSessionId"] = normalize_session_id(lease_owner_session_id)
    if lease_expires_at_ms is not None:
        payload["leaseExpiresAtMs"] = int(lease_expires_at_ms)
    if updated_at_ms is not None:
        payload["updatedAtMs"] = int(updated_at_ms)
    return payload
