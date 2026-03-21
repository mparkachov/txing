from __future__ import annotations

from typing import Any

DEFAULT_STREAM_PATH = "board-cam"
DEFAULT_MEDIAMTX_VIEWER_PORT = 8889
DEFAULT_VIDEO_CODEC = "h264"
MEDIA_STATUS_STARTING = "starting"
MEDIA_STATUS_READY = "ready"
MEDIA_STATUS_ERROR = "error"
VALID_MEDIA_STATUSES = {
    MEDIA_STATUS_STARTING,
    MEDIA_STATUS_READY,
    MEDIA_STATUS_ERROR,
}


def default_media_state_payload() -> dict[str, Any]:
    return {
        "status": MEDIA_STATUS_STARTING,
        "ready": False,
        "local": {
            "viewerUrl": None,
            "streamPath": None,
        },
        "codec": {
            "video": None,
        },
        # MediaMTX owns browser sessions in the MVP, so consumer lifecycle is not
        # surfaced to the local Python state reporter.
        "viewerConnected": False,
        "lastError": None,
        "updatedAt": None,
    }


def normalize_media_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = default_media_state_payload()
    if not isinstance(payload, dict):
        return normalized

    status = payload.get("status")
    if isinstance(status, str) and status in VALID_MEDIA_STATUSES:
        normalized["status"] = status

    ready = payload.get("ready")
    if isinstance(ready, bool):
        normalized["ready"] = ready

    local = payload.get("local")
    if isinstance(local, dict):
        viewer_url = local.get("viewerUrl")
        if isinstance(viewer_url, str) and viewer_url.strip():
            normalized["local"]["viewerUrl"] = viewer_url.strip()

        stream_path = local.get("streamPath")
        if isinstance(stream_path, str) and stream_path.strip():
            normalized["local"]["streamPath"] = stream_path.strip().strip("/")

    codec = payload.get("codec")
    if isinstance(codec, dict):
        video_codec = codec.get("video")
        if isinstance(video_codec, str) and video_codec.strip():
            normalized["codec"]["video"] = video_codec.strip()

    viewer_connected = payload.get("viewerConnected")
    if isinstance(viewer_connected, bool):
        normalized["viewerConnected"] = viewer_connected

    last_error = payload.get("lastError")
    if isinstance(last_error, str) and last_error.strip():
        normalized["lastError"] = last_error.strip()

    updated_at = payload.get("updatedAt")
    if isinstance(updated_at, str) and updated_at.strip():
        normalized["updatedAt"] = updated_at.strip()

    return normalized


def build_reported_media_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_media_state(payload)
    return {
        "status": normalized["status"],
        "ready": normalized["ready"],
        "local": {
            "viewerUrl": normalized["local"]["viewerUrl"],
            "streamPath": normalized["local"]["streamPath"],
        },
        "codec": {
            "video": normalized["codec"]["video"],
        },
        "viewerConnected": normalized["viewerConnected"],
        "lastError": normalized["lastError"],
    }
