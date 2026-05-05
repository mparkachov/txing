from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class BleStackConfig:
    os: str
    backend: str
    adapter: str | None = None
    scanner_kwargs: dict[str, Any] = field(default_factory=dict)
    client_kwargs: dict[str, Any] = field(default_factory=dict)

    def event_fields(self) -> dict[str, object]:
        return {
            "os": self.os,
            "backend": self.backend,
            "adapter": self.adapter,
        }


def detect_ble_stack(
    *,
    adapter: str | None = None,
    sys_platform: str | None = None,
) -> BleStackConfig:
    platform_name = sys_platform or sys.platform
    clean_adapter = adapter or None

    if platform_name == "darwin":
        return BleStackConfig(os="macos", backend="corebluetooth")
    if platform_name.startswith("linux"):
        kwargs = {"adapter": clean_adapter} if clean_adapter else {}
        return BleStackConfig(
            os="linux",
            backend="bluez",
            adapter=clean_adapter,
            scanner_kwargs=kwargs,
            client_kwargs=kwargs,
        )
    if platform_name.startswith("win"):
        return BleStackConfig(os="windows", backend="winrt")
    return BleStackConfig(os=platform_name, backend="bleak-auto")
