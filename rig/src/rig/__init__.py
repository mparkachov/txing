from __future__ import annotations


def main() -> int | None:
    from .device_process import main as device_process_main

    return device_process_main()

__all__ = ["main"]
