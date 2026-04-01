from __future__ import annotations


def main() -> int | None:
    from .ble_bridge import main as bridge_main

    return bridge_main()

__all__ = ["main"]
