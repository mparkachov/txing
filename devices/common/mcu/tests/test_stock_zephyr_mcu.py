from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_stock_zephyr_mcu():
    script = Path(__file__).resolve().parents[1] / "scripts" / "stock_zephyr_mcu.py"
    spec = importlib.util.spec_from_file_location("stock_zephyr_mcu", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_power_si_debug_build_dir_is_separate_from_release() -> None:
    mcu = load_stock_zephyr_mcu()

    assert mcu.build_dir("power-si").name == "zephyr-xiao_mg24"
    assert mcu.build_dir("power-si", debug=True).name == "zephyr-xiao_mg24-debug"


def test_power_si_debug_flash_uses_debug_build_directory() -> None:
    mcu = load_stock_zephyr_mcu()

    release_command = [str(part) for part in mcu.west_flash_command("power-si")]
    debug_command = [str(part) for part in mcu.west_flash_command("power-si", debug=True)]

    assert release_command[release_command.index("-d") + 1].endswith(
        "devices/power-si/mcu/build/zephyr-xiao_mg24"
    )
    assert debug_command[debug_command.index("-d") + 1].endswith(
        "devices/power-si/mcu/build/zephyr-xiao_mg24-debug"
    )
    assert "--pyocd" in debug_command
