from __future__ import annotations


def main() -> None:
    from .sparkplug_manager import main as sparkplug_manager_main

    sparkplug_manager_main()


__all__ = ["main"]
