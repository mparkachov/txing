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


def test_power_nrf_uses_dedicated_lm20a_build_profiles_and_stock_openocd() -> None:
    mcu = load_stock_zephyr_mcu()

    config = mcu.device_config("power-nrf")
    assert config.board == "xiao_nrf54lm20a/nrf54lm20a/cpuapp"
    assert config.flash_runner == "openocd-nrf54lm20a"
    assert mcu.build_dir("power-nrf").name == "zephyr-xiao_nrf54lm20a_nrf54lm20a_cpuapp"
    assert (
        mcu.build_dir("power-nrf", profile="debug").name
        == "zephyr-xiao_nrf54lm20a_nrf54lm20a_cpuapp-debug"
    )
    assert (
        mcu.build_dir("power-nrf", profile="sed-debug").name
        == "zephyr-xiao_nrf54lm20a_nrf54lm20a_cpuapp-sed-debug"
    )

    release_profile = mcu.build_profile("power-nrf")
    debug_profile = mcu.build_profile("power-nrf", profile="debug")
    sed_debug_profile = mcu.build_profile("power-nrf", profile="sed-debug")
    assert release_profile.release_conf
    assert debug_profile.debug_conf
    assert sed_debug_profile.debug_conf and sed_debug_profile.sed_debug_conf
    assert mcu.isolated_patches_for_device("power-nrf") == ()

    command = [str(part) for part in mcu.openocd_command("power-nrf", Path("factory.hex"))]
    assert str(mcu.POWER_NRF_OPENOCD_CFG) in command
    assert "targets nrf54lm20a.cpu" in command
    assert "nrf54lm20a-load factory.hex" in command
    assert "verify_image factory.hex" in command


def test_power_nrf_factory_command_uses_txn1_writer(monkeypatch) -> None:
    mcu = load_stock_zephyr_mcu()
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append([str(arg) for arg in args])
        return None

    monkeypatch.setattr(mcu, "run", fake_run)
    mcu.build_power_nrf_factory_hex(
        "power-nrf-001",
        Path("dataset.hex"),
        Path("output.hex"),
        5683,
    )

    assert calls == [
        [
            str(mcu.sys.executable),
            str(mcu.POWER_NRF_FACTORY_SCRIPT),
            "write-hex",
            "power-nrf-001",
            "--dataset-tlvs",
            "dataset.hex",
            "--port",
            "5683",
            "--output",
            "output.hex",
        ]
    ]
    assert mcu.ACTIVE_BUILD_PROFILES == (
        "release",
        "debug",
        "sed-debug",
    )


def test_power_si_sed_debug_profile_uses_debug_and_sed_overlays() -> None:
    mcu = load_stock_zephyr_mcu()

    debug_profile = mcu.build_profile("power-si", profile="sed-debug")
    config = mcu.device_config("power-si")

    assert debug_profile.debug_conf
    assert debug_profile.sed_debug_conf
    assert debug_profile.use_silabs_ccm_candidate
    assert config.sed_debug_conf is not None
    assert config.sed_debug_conf.name == "sed-debug.conf"


def test_power_si_release_profile_reuses_the_sed_debug_functional_overlay() -> None:
    mcu = load_stock_zephyr_mcu()

    release_profile = mcu.build_profile("power-si")
    config = mcu.device_config("power-si")

    assert not release_profile.debug_conf
    assert release_profile.sed_debug_conf
    assert release_profile.release_conf
    assert release_profile.use_silabs_ccm_candidate
    assert config.release_conf is not None
    assert config.release_conf.name == "release.conf"


def test_power_si_debug_flash_uses_debug_build_directory() -> None:
    mcu = load_stock_zephyr_mcu()

    release_command = [str(part) for part in mcu.west_flash_command("power-si")]
    debug_command = [str(part) for part in mcu.west_flash_command("power-si", debug=True)]
    sed_debug_command = [
        str(part) for part in mcu.west_flash_command("power-si", profile="sed-debug")
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
    assert "--pyocd" in debug_command

    sed_debug_hex = mcu.firmware_hex("power-si", profile="sed-debug")
    explicit_command = [
        str(part)
        for part in mcu.west_flash_command(
            "power-si", sed_debug_hex, profile="sed-debug"
        )
    ]
    assert explicit_command[explicit_command.index("--hex-file") + 1] == str(sed_debug_hex)


def test_power_si_sed_candidate_patch_is_used_by_release_and_sed_debug() -> None:
    mcu = load_stock_zephyr_mcu()
    previous = os.environ.pop(mcu.POWER_SI_SILABS_CCM_PATCH_ENV, None)

    try:
        assert mcu.isolated_patches_for_device("power-si", profile="debug") == ()
        assert mcu.isolated_patches_for_device("power") == ()

        release_patches = mcu.isolated_patches_for_device("power-si")
        assert [patch.patch.name for patch in release_patches] == [
            "silabs-radioaes-zero-length-ccm.patch",
        ]
        assert [patch.checkout.name for patch in release_patches] == ["silabs"]

        sed_debug_patches = mcu.isolated_patches_for_device(
            "power-si", profile="sed-debug"
        )
        assert [patch.patch.name for patch in sed_debug_patches] == [
            "silabs-radioaes-zero-length-ccm.patch",
        ]
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
