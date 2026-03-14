from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_SHADOW_FILE = Path("/tmp/txing_board_shadow.json")


def default_shadow_payload() -> dict[str, Any]:
    return {
        "state": {
            "reported": {
                "board": {}
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
