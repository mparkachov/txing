from __future__ import annotations

import argparse
from pathlib import Path

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
    return parser


def wake_main() -> None:
    args = _build_parser("wake").parse_args()
    _touch(args.wake_file, "sleep=false\n")
    _remove_if_exists(args.sleep_file)
    print(f"Created {args.wake_file} and removed {args.sleep_file} (if present)")


def sleep_main() -> None:
    args = _build_parser("sleep").parse_args()
    _touch(args.sleep_file, "sleep=true\n")
    _remove_if_exists(args.wake_file)
    print(f"Created {args.sleep_file} and removed {args.wake_file} (if present)")
