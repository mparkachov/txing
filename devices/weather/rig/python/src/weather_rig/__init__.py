from __future__ import annotations


def main() -> None:
    from .sparkplug_manager import main as sparkplug_main

    sparkplug_main()


__all__ = ["main"]
