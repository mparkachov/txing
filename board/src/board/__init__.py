from __future__ import annotations


def main() -> None:
    from .shadow_control import main as shadow_control_main

    shadow_control_main()


__all__ = ["main"]
