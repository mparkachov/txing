from __future__ import annotations

import importlib.util
import os
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
    assert mcu.build_dir("power-si", profile="debug").name == "zephyr-xiao_mg24-debug"
    assert (
        mcu.build_dir("power-si", profile="sed-debug").name
        == "zephyr-xiao_mg24-sed-debug"
    )
    assert (
        mcu.build_dir("power-si", profile="sed-current").name
        == "zephyr-xiao_mg24-sed-current"
    )


def test_power_si_debug_flash_uses_debug_build_directory() -> None:
    mcu = load_stock_zephyr_mcu()

    release_command = [str(part) for part in mcu.west_flash_command("power-si")]
    debug_command = [str(part) for part in mcu.west_flash_command("power-si", debug=True)]
    sed_debug_command = [
        str(part) for part in mcu.west_flash_command("power-si", profile="sed-debug")
    ]
    sed_current_command = [
        str(part) for part in mcu.west_flash_command("power-si", profile="sed-current")
    ]

    assert release_command[release_command.index("-d") + 1].endswith(
        "devices/power-si/mcu/build/zephyr-xiao_mg24"
    )
    assert debug_command[debug_command.index("-d") + 1].endswith(
        "devices/power-si/mcu/build/zephyr-xiao_mg24-debug"
    )
    assert sed_debug_command[sed_debug_command.index("-d") + 1].endswith(
        "devices/power-si/mcu/build/zephyr-xiao_mg24-sed-debug"
    )
    assert sed_current_command[sed_current_command.index("-d") + 1].endswith(
        "devices/power-si/mcu/build/zephyr-xiao_mg24-sed-current"
    )
    assert "--pyocd" in debug_command


def test_power_si_sed_test_patch_is_opt_in() -> None:
    mcu = load_stock_zephyr_mcu()
    previous = os.environ.pop(mcu.POWER_SI_SED_TEST_PATCH_ENV, None)

    try:
        assert mcu.zephyr_test_patches_for_device("power-si") == ()
        assert mcu.zephyr_test_patches_for_device("power-si", profile="debug") == ()
        assert mcu.zephyr_test_patches_for_device("power") == ()

        profile_patches = mcu.zephyr_test_patches_for_device(
            "power-si", profile="sed-debug"
        )
        assert [patch.patch.name for patch in profile_patches] == [
            "silabs-efr32-sed-data-poll-rx-test.patch",
        ]
        current_patches = mcu.zephyr_test_patches_for_device(
            "power-si", profile="sed-current"
        )
        assert current_patches == profile_patches

        os.environ[mcu.POWER_SI_SED_TEST_PATCH_ENV] = "1"
        patches = mcu.zephyr_test_patches_for_device("power-si")

        assert [patch.patch.name for patch in patches] == [
            "silabs-efr32-sed-data-poll-rx-test.patch",
        ]
        assert [patch.checkout.name for patch in patches] == ["zephyr"]
        for patch in patches:
            assert patch.patch.exists()
        assert mcu.zephyr_test_patches_for_device("power") == ()
    finally:
        if previous is None:
            os.environ.pop(mcu.POWER_SI_SED_TEST_PATCH_ENV, None)
        else:
            os.environ[mcu.POWER_SI_SED_TEST_PATCH_ENV] = previous
