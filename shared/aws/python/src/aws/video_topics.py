from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VIDEO_TOPIC_NAMESPACE = "txings"
VIDEO_SERVICE_NAME = "video"
VIDEO_TRANSPORT = "aws-webrtc"
VIDEO_DEFAULT_CODEC = "h264"
VIDEO_STATUS_STARTING = "starting"
VIDEO_STATUS_READY = "ready"
VIDEO_STATUS_ERROR = "error"
VIDEO_STATUS_UNAVAILABLE = "unavailable"
VALID_VIDEO_STATUSES = {
    VIDEO_STATUS_STARTING,
    VIDEO_STATUS_READY,
    VIDEO_STATUS_ERROR,
    VIDEO_STATUS_UNAVAILABLE,
}


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
class VideoTopics:
    topic_root: str
    descriptor: str
    status: str


def build_video_topic_root(device_id: str) -> str:
    normalized = normalize_device_id(device_id)
    return f"{VIDEO_TOPIC_NAMESPACE}/{normalized}/{VIDEO_SERVICE_NAME}"


def build_video_descriptor_topic(device_id: str) -> str:
    return f"{build_video_topic_root(device_id)}/descriptor"


def build_video_status_topic(device_id: str) -> str:
    return f"{build_video_topic_root(device_id)}/status"


def build_video_topics(device_id: str) -> VideoTopics:
    topic_root = build_video_topic_root(device_id)
    return VideoTopics(
        topic_root=topic_root,
        descriptor=f"{topic_root}/descriptor",
        status=f"{topic_root}/status",
    )


def parse_video_descriptor_or_status_topic(topic: str) -> tuple[str, str] | None:
    parts = topic.split("/")
    if len(parts) != 4:
        return None
    if parts[0] != VIDEO_TOPIC_NAMESPACE or parts[2] != VIDEO_SERVICE_NAME:
        return None
    kind = parts[3]
    if kind not in {"descriptor", "status"}:
        return None
    device_id = parts[1]
    if not device_id:
        return None
    return device_id, kind


def build_video_descriptor_payload(
    *,
    device_id: str,
    channel_name: str,
    region: str,
    server_version: str,
    transport: str = VIDEO_TRANSPORT,
    codec_video: str | None = VIDEO_DEFAULT_CODEC,
) -> dict[str, Any]:
    topics = build_video_topics(device_id)
    return {
        "serviceId": VIDEO_SERVICE_NAME,
        "serverInfo": {
            "name": VIDEO_SERVICE_NAME,
            "version": server_version,
        },
        "topicRoot": topics.topic_root,
        "descriptorTopic": topics.descriptor,
        "statusTopic": topics.status,
        "transport": transport,
        "channelName": _normalize_segment(channel_name, field_name="channel_name"),
        "region": _normalize_segment(region, field_name="region"),
        "codec": {
            "video": codec_video,
        },
        "serverVersion": server_version,
    }


def build_video_status_payload(
    *,
    available: bool,
    ready: bool,
    status: str,
    viewer_connected: bool = False,
    last_error: str | None = None,
    updated_at_ms: int | None = None,
) -> dict[str, Any]:
    if status not in VALID_VIDEO_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_VIDEO_STATUSES)}")
    payload: dict[str, Any] = {
        "serviceId": VIDEO_SERVICE_NAME,
        "available": bool(available),
        "ready": bool(ready),
        "status": status,
        "viewerConnected": bool(viewer_connected),
        "lastError": last_error if last_error is None else str(last_error),
    }
    if updated_at_ms is not None:
        payload["updatedAtMs"] = int(updated_at_ms)
    return payload
