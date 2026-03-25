from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_VIDEO_CHANNEL_NAME = "txing-board-video"
DEFAULT_VIDEO_CODEC = "h264"
DEFAULT_VIDEO_STATE_FILE = Path("/tmp/txing_board_video_state.json")
VIDEO_TRANSPORT = "aws-webrtc"
VIDEO_STATUS_STARTING = "starting"
VIDEO_STATUS_READY = "ready"
VIDEO_STATUS_ERROR = "error"
VALID_VIDEO_STATUSES = {
    VIDEO_STATUS_STARTING,
    VIDEO_STATUS_READY,
    VIDEO_STATUS_ERROR,
}


def default_video_state_payload(
    *,
    viewer_url: str | None = None,
    channel_name: str = DEFAULT_VIDEO_CHANNEL_NAME,
) -> dict[str, Any]:
    return {
        "status": VIDEO_STATUS_STARTING,
        "ready": False,
        "transport": VIDEO_TRANSPORT,
        "session": {
            "viewerUrl": viewer_url,
            "channelName": channel_name,
        },
        "codec": {
            "video": DEFAULT_VIDEO_CODEC,
        },
        "viewerConnected": False,
        "lastError": None,
        "updatedAt": None,
    }


def normalize_video_state(
    payload: dict[str, Any] | None,
    *,
    viewer_url: str | None = None,
    channel_name: str = DEFAULT_VIDEO_CHANNEL_NAME,
) -> dict[str, Any]:
    normalized = default_video_state_payload(
        viewer_url=viewer_url,
        channel_name=channel_name,
    )
    if not isinstance(payload, dict):
        return normalized

    status = payload.get("status")
    if isinstance(status, str) and status in VALID_VIDEO_STATUSES:
        normalized["status"] = status

    ready = payload.get("ready")
    if isinstance(ready, bool):
        normalized["ready"] = ready

    transport = payload.get("transport")
    if transport == VIDEO_TRANSPORT:
        normalized["transport"] = transport

    session = payload.get("session")
    if isinstance(session, dict):
        session_viewer_url = session.get("viewerUrl")
        if isinstance(session_viewer_url, str) and session_viewer_url.strip():
            normalized["session"]["viewerUrl"] = session_viewer_url.strip()

        session_channel_name = session.get("channelName")
        if isinstance(session_channel_name, str) and session_channel_name.strip():
            normalized["session"]["channelName"] = session_channel_name.strip()

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


def load_video_state(
    state_file: Path,
    *,
    viewer_url: str | None = None,
    channel_name: str = DEFAULT_VIDEO_CHANNEL_NAME,
) -> dict[str, Any]:
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_video_state_payload(
            viewer_url=viewer_url,
            channel_name=channel_name,
        )
    except (OSError, json.JSONDecodeError):
        return {
            **default_video_state_payload(
                viewer_url=viewer_url,
                channel_name=channel_name,
            ),
            "status": VIDEO_STATUS_ERROR,
            "lastError": f"invalid video sender state file: {state_file}",
        }
    if not isinstance(payload, dict):
        return {
            **default_video_state_payload(
                viewer_url=viewer_url,
                channel_name=channel_name,
            ),
            "status": VIDEO_STATUS_ERROR,
            "lastError": f"invalid video sender state payload: {state_file}",
        }
    return normalize_video_state(
        payload,
        viewer_url=viewer_url,
        channel_name=channel_name,
    )


def build_reported_video_state(
    payload: dict[str, Any] | None,
    *,
    viewer_url: str | None = None,
    channel_name: str = DEFAULT_VIDEO_CHANNEL_NAME,
) -> dict[str, Any]:
    normalized = normalize_video_state(
        payload,
        viewer_url=viewer_url,
        channel_name=channel_name,
    )
    return {
        "status": normalized["status"],
        "ready": normalized["ready"],
        "transport": normalized["transport"],
        "session": {
            "viewerUrl": normalized["session"]["viewerUrl"],
            "channelName": normalized["session"]["channelName"],
        },
        "codec": {
            "video": normalized["codec"]["video"],
        },
        "viewerConnected": normalized["viewerConnected"],
        "lastError": normalized["lastError"],
    }
