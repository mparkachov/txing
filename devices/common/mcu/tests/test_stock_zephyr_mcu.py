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


def test_power_si_sed_profiles_use_distinct_overlays() -> None:
    mcu = load_stock_zephyr_mcu()

    debug_profile = mcu.build_profile("power-si", profile="sed-debug")
    config = mcu.device_config("power-si")

    assert debug_profile.debug_conf
    assert debug_profile.sed_debug_conf
    assert not debug_profile.current_conf
    assert debug_profile.use_silabs_ccm_candidate
    assert config.sed_debug_conf is not None
    assert config.sed_debug_conf.name == "sed-debug.conf"

    current_profile = mcu.build_profile("power-si", profile="sed-current")
    assert not current_profile.debug_conf
    assert not current_profile.sed_debug_conf
    assert current_profile.current_conf
    assert current_profile.use_silabs_ccm_candidate
    assert config.current_conf is not None
    assert config.current_conf.name == "current.conf"


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

    sed_debug_hex = mcu.firmware_hex("power-si", profile="sed-debug")
    explicit_command = [
        str(part)
        for part in mcu.west_flash_command(
            "power-si", sed_debug_hex, profile="sed-debug"
        )
    ]
    assert explicit_command[explicit_command.index("--hex-file") + 1] == str(sed_debug_hex)

def test_power_si_sed_candidate_patch_is_opt_in() -> None:
    mcu = load_stock_zephyr_mcu()
    previous = os.environ.pop(mcu.POWER_SI_SILABS_CCM_PATCH_ENV, None)

    try:
        assert mcu.isolated_patches_for_device("power-si") == ()
        assert mcu.isolated_patches_for_device("power-si", profile="debug") == ()
        assert mcu.isolated_patches_for_device("power") == ()

        profile_patches = mcu.isolated_patches_for_device(
            "power-si", profile="sed-debug"
        )
        assert [patch.patch.name for patch in profile_patches] == [
            "silabs-radioaes-zero-length-ccm.patch",
        ]
        current_patches = mcu.isolated_patches_for_device(
            "power-si", profile="sed-current"
        )
        assert current_patches == profile_patches
        os.environ[mcu.POWER_SI_SILABS_CCM_PATCH_ENV] = "1"
        patches = mcu.isolated_patches_for_device("power-si")

        assert [patch.patch.name for patch in patches] == [
            "silabs-radioaes-zero-length-ccm.patch",
        ]
        assert [patch.checkout.name for patch in patches] == ["silabs"]
        for patch in patches:
            assert patch.patch.exists()
        patch_text = patches[0].patch.read_text()
        assert "sli_protocol_crypto_radioaes.c" in patch_text
        assert "aes_ccm_radio_encrypt_empty_payload" in patch_text
        assert "sli_aes_crypt_ecb_radio" in patch_text
        assert "encrypt && length == 0 && tag_length > 0" in patch_text
        assert "ver_failed" in patch_text
        assert "zero_payload" not in patch_text
        assert "corrected zero-payload" not in patch_text
        assert "IEEE802154_HW_TX_SEC" not in patch_text
        assert "SED test:" not in patch_text
        assert "ieee802154_silabs_efr32.c" not in patch_text
        assert "LOG_" not in patch_text
        assert "printk" not in patch_text
        assert "printf" not in patch_text
        assert mcu.isolated_patches_for_device("power") == ()
    finally:
        if previous is None:
            os.environ.pop(mcu.POWER_SI_SILABS_CCM_PATCH_ENV, None)
        else:
            os.environ[mcu.POWER_SI_SILABS_CCM_PATCH_ENV] = previous
