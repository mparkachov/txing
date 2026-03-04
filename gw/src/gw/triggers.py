from __future__ import annotations

import argparse
import json
from pathlib import Path

from .shadow_store import (
    DEFAULT_SHADOW_FILE,
    load_shadow,
)

DEFAULT_WAKE_FILE = Path("/tmp/wake")
DEFAULT_SLEEP_FILE = Path("/tmp/sleep")


def _touch(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _remove_if_exists(path: Path) -> None:
    path.unlink(missing_ok=True)


def _build_parser(action: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=action,
        description=f"Create {action} trigger file for gw BLE bridge",
    )
    parser.add_argument(
        "--wake-file",
        type=Path,
        default=DEFAULT_WAKE_FILE,
        help="Path to wake trigger file (default: /tmp/wake)",
    )
    parser.add_argument(
        "--sleep-file",
        type=Path,
        default=DEFAULT_SLEEP_FILE,
        help="Path to sleep trigger file (default: /tmp/sleep)",
    )
    parser.add_argument(
        "--shadow-file",
        type=Path,
        default=DEFAULT_SHADOW_FILE,
        help="Path to simulated shadow snapshot file (default: /tmp/txing_shadow.json)",
    )
    return parser


def wake_main() -> None:
    args = _build_parser("wake").parse_args()
    _touch(args.wake_file, "desired.mcu.power=true\n")
    _remove_if_exists(args.sleep_file)
    print(
        f"Created wake trigger {args.wake_file}; "
        f"removed {args.sleep_file} (if present). "
        f"Simulated shadow will be updated by gw only."
    )


def sleep_main() -> None:
    args = _build_parser("sleep").parse_args()
    _touch(args.sleep_file, "desired.mcu.power=false\n")
    _remove_if_exists(args.wake_file)
    print(
        f"Created sleep trigger {args.sleep_file}; "
        f"removed {args.wake_file} (if present). "
        f"Simulated shadow will be updated by gw only."
    )


def print_main() -> None:
    parser = argparse.ArgumentParser(
        prog="print",
        description="Print current simulated AWS IoT shadow state",
    )
    parser.add_argument(
        "--shadow-file",
        type=Path,
        default=DEFAULT_SHADOW_FILE,
        help="Path to simulated shadow snapshot file (default: /tmp/txing_shadow.json)",
    )
    args = parser.parse_args()
    payload = load_shadow(args.shadow_file)
    print(json.dumps(payload, sort_keys=True, indent=2))
