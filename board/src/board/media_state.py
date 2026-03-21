from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_MEDIA_STATE_FILE = Path("/run/txing/board-media/state.json")
DEFAULT_STREAM_PATH = "board-cam"
DEFAULT_MEDIAMTX_RTSP_PORT = 8554
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


def media_state_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def load_media_state(path: Path = DEFAULT_MEDIA_STATE_FILE) -> dict[str, Any]:
    if not path.exists():
        return default_media_state_payload()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_media_state_payload()

    if not isinstance(data, dict):
        return default_media_state_payload()
    return normalize_media_state(data)


def save_media_state(payload: dict[str, Any], path: Path = DEFAULT_MEDIA_STATE_FILE) -> None:
    normalized = normalize_media_state(payload)
    if normalized["updatedAt"] is None:
        normalized["updatedAt"] = media_state_timestamp()

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(f"{json.dumps(normalized, sort_keys=True)}\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
