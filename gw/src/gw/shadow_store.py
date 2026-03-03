from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

POWER_ON = "on"
POWER_OFF = "off"
DEFAULT_SHADOW_FILE = Path("/tmp/txing_shadow.json")


def default_shadow_payload() -> dict[str, Any]:
    return {
        "state": {
            "reported": {"mcu": {"power": POWER_OFF}},
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


def get_desired_power(payload: dict[str, Any]) -> str | None:
    desired = payload.get("state", {}).get("desired", {})
    mcu = desired.get("mcu", {}) if isinstance(desired, dict) else {}
    value = mcu.get("power") if isinstance(mcu, dict) else None
    return value if isinstance(value, str) else None


def get_reported_power(payload: dict[str, Any]) -> str:
    reported = payload.get("state", {}).get("reported", {})
    mcu = reported.get("mcu", {}) if isinstance(reported, dict) else {}
    value = mcu.get("power") if isinstance(mcu, dict) else None
    if isinstance(value, str):
        return value
    return POWER_OFF


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
