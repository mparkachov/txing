from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_REPORTED_POWER = False
DEFAULT_REPORTED_ONLINE = False
DEFAULT_BATTERY_MV = 3750
DEFAULT_BOARD_POWER = False
DEFAULT_BOARD_WIFI_ONLINE = False
DEFAULT_REDCON = 4
DEFAULT_SHADOW_FILE = Path("/tmp/txing_shadow.json")


def default_shadow_payload() -> dict[str, Any]:
    return {
        "state": {
            "reported": {
                "redcon": DEFAULT_REDCON,
                "device": {
                    "batteryMv": DEFAULT_BATTERY_MV,
                    "mcu": {
                        "power": DEFAULT_REPORTED_POWER,
                        "online": DEFAULT_REPORTED_ONLINE,
                    },
                    "board": {
                        "power": DEFAULT_BOARD_POWER,
                        "wifi": {
                            "online": DEFAULT_BOARD_WIFI_ONLINE,
                        },
                    },
                },
            },
        }
    }


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


def _get_reported_device(payload: dict[str, Any]) -> dict[str, Any]:
    reported = payload.get("state", {}).get("reported", {})
    device = reported.get("device", {}) if isinstance(reported, dict) else {}
    return device if isinstance(device, dict) else {}


def get_reported_power(payload: dict[str, Any]) -> bool:
    device = _get_reported_device(payload)
    mcu = device.get("mcu", {}) if isinstance(device, dict) else {}
    value = mcu.get("power") if isinstance(mcu, dict) else None
    if isinstance(value, bool):
        return value
    return DEFAULT_REPORTED_POWER


def get_reported_battery_mv(payload: dict[str, Any]) -> int:
    device = _get_reported_device(payload)
    value = device.get("batteryMv") if isinstance(device, dict) else None
    if isinstance(value, bool):
        return DEFAULT_BATTERY_MV
    if isinstance(value, int) and 0 <= value <= 10000:
        return value
    return DEFAULT_BATTERY_MV


def get_reported_board_power(payload: dict[str, Any]) -> bool:
    device = _get_reported_device(payload)
    board = device.get("board", {}) if isinstance(device, dict) else {}
    value = board.get("power") if isinstance(board, dict) else None
    if isinstance(value, bool):
        return value
    return DEFAULT_BOARD_POWER


def get_reported_board_wifi_online(payload: dict[str, Any]) -> bool:
    device = _get_reported_device(payload)
    board = device.get("board", {}) if isinstance(device, dict) else {}
    wifi = board.get("wifi", {}) if isinstance(board, dict) else {}
    value = wifi.get("online") if isinstance(wifi, dict) else None
    if isinstance(value, bool):
        return value
    return DEFAULT_BOARD_WIFI_ONLINE


def get_reported_redcon(payload: dict[str, Any]) -> int:
    reported = payload.get("state", {}).get("reported", {})
    value = reported.get("redcon") if isinstance(reported, dict) else None
    if isinstance(value, int) and 1 <= value <= 4:
        return value
    return DEFAULT_REDCON
