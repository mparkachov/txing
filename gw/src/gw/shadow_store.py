from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_REPORTED_POWER = False
DEFAULT_BATTERY_MV = 3750
DEFAULT_BOARD_POWER = False
DEFAULT_BOARD_WIFI_ONLINE = False
DEFAULT_BOARD_VIDEO_READY = False
DEFAULT_BOARD_VIDEO_VIEWER_CONNECTED = False
DEFAULT_REDCON = 4
DEFAULT_DESIRED_REDCON: int | None = None
DEFAULT_SHADOW_FILE = Path("/tmp/txing_shadow.json")


def default_shadow_payload() -> dict[str, Any]:
    return {
        "state": {
            "desired": {
                "redcon": DEFAULT_DESIRED_REDCON,
                "board": {
                    "power": None,
                },
            },
            "reported": {
                "redcon": DEFAULT_REDCON,
                "batteryMv": DEFAULT_BATTERY_MV,
                "mcu": {
                    "power": DEFAULT_REPORTED_POWER,
                },
                "board": {
                    "power": DEFAULT_BOARD_POWER,
                    "wifi": {
                        "online": DEFAULT_BOARD_WIFI_ONLINE,
                    },
                    "video": {
                        "ready": DEFAULT_BOARD_VIDEO_READY,
                        "viewerConnected": DEFAULT_BOARD_VIDEO_VIEWER_CONNECTED,
                    },
                },
            },
        }
    }


def get_desired_redcon(payload: dict[str, Any]) -> int | None:
    desired = payload.get("state", {}).get("desired", {})
    value = desired.get("redcon") if isinstance(desired, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 1 <= value <= 4:
        return value
    return None


def get_desired_board_power(payload: dict[str, Any]) -> bool | None:
    desired = payload.get("state", {}).get("desired", {})
    board = desired.get("board", {}) if isinstance(desired, dict) else {}
    value = board.get("power") if isinstance(board, dict) else None
    return value if isinstance(value, bool) else None


def load_shadow(path: Path = DEFAULT_SHADOW_FILE) -> dict[str, Any]:
    if not path.exists():
        return default_shadow_payload()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_shadow_payload()

    if not isinstance(data, dict):
        return default_shadow_payload()
    return data


def save_shadow(payload: dict[str, Any], path: Path = DEFAULT_SHADOW_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(f"{json.dumps(payload, sort_keys=True)}\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def get_desired_power(payload: dict[str, Any]) -> bool | None:
    desired = payload.get("state", {}).get("desired", {})
    mcu = desired.get("mcu", {}) if isinstance(desired, dict) else {}
    value = mcu.get("power") if isinstance(mcu, dict) else None
    return value if isinstance(value, bool) else None


def get_reported_power(payload: dict[str, Any]) -> bool:
    reported = payload.get("state", {}).get("reported", {})
    mcu = reported.get("mcu", {}) if isinstance(reported, dict) else {}
    value = mcu.get("power") if isinstance(mcu, dict) else None
    if isinstance(value, bool):
        return value
    return DEFAULT_REPORTED_POWER


def get_reported_battery_mv(payload: dict[str, Any]) -> int:
    reported = payload.get("state", {}).get("reported", {})
    value = reported.get("batteryMv") if isinstance(reported, dict) else None
    if isinstance(value, bool):
        return DEFAULT_BATTERY_MV
    if isinstance(value, int) and 0 <= value <= 10000:
        return value
    return DEFAULT_BATTERY_MV


def get_reported_board_power(payload: dict[str, Any]) -> bool:
    reported = payload.get("state", {}).get("reported", {})
    board = reported.get("board", {}) if isinstance(reported, dict) else {}
    value = board.get("power") if isinstance(board, dict) else None
    if isinstance(value, bool):
        return value
    return DEFAULT_BOARD_POWER


def get_reported_board_wifi_online(payload: dict[str, Any]) -> bool:
    reported = payload.get("state", {}).get("reported", {})
    board = reported.get("board", {}) if isinstance(reported, dict) else {}
    wifi = board.get("wifi", {}) if isinstance(board, dict) else {}
    value = wifi.get("online") if isinstance(wifi, dict) else None
    if isinstance(value, bool):
        return value
    return DEFAULT_BOARD_WIFI_ONLINE


def get_reported_board_video_ready(payload: dict[str, Any]) -> bool:
    reported = payload.get("state", {}).get("reported", {})
    board = reported.get("board", {}) if isinstance(reported, dict) else {}
    video = board.get("video", {}) if isinstance(board, dict) else {}
    value = video.get("ready") if isinstance(video, dict) else None
    if isinstance(value, bool):
        return value
    return DEFAULT_BOARD_VIDEO_READY


def get_reported_board_video_viewer_connected(payload: dict[str, Any]) -> bool:
    reported = payload.get("state", {}).get("reported", {})
    board = reported.get("board", {}) if isinstance(reported, dict) else {}
    video = board.get("video", {}) if isinstance(board, dict) else {}
    value = video.get("viewerConnected") if isinstance(video, dict) else None
    if isinstance(value, bool):
        return value
    return DEFAULT_BOARD_VIDEO_VIEWER_CONNECTED


def get_reported_redcon(payload: dict[str, Any]) -> int:
    reported = payload.get("state", {}).get("reported", {})
    value = reported.get("redcon") if isinstance(reported, dict) else None
    if isinstance(value, int) and 1 <= value <= 4:
        return value
    return DEFAULT_REDCON


def clear_desired_if_synced(path: Path = DEFAULT_SHADOW_FILE) -> dict[str, Any]:
    payload = load_shadow(path)
    desired_power = get_desired_power(payload)
    reported_power = get_reported_power(payload)
    if desired_power is None or desired_power != reported_power:
        return payload

    state = payload.setdefault("state", {})
    if isinstance(state, dict):
        state.pop("desired", None)
    save_shadow(payload, path)
    return payload
