#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


BLE_DEBUG_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BLE_DEBUG_DIR.parents[2]
NRF_BM_DIR = PROJECT_ROOT / "devices" / "common" / "mcu" / "nrf-bm"
NRF_BM_TOOLCHAIN_SCRIPT = NRF_BM_DIR / "scripts" / "toolchain.py"
PRODUCTION_WEATHER_MCU_DIR = PROJECT_ROOT / "devices" / "weather" / "mcu"
FIRMWARE_DIR = BLE_DEBUG_DIR / "firmware"
BUILD_DIR = BLE_DEBUG_DIR / "build" / "baremetal-weather-ble-debug"
GENERATED_DIR = BLE_DEBUG_DIR / ".generated"
DEFAULT_PROFILE = "baseline-100-0-6"
DEFAULT_FLASH_RETRIES = 3
DEFAULT_FLASH_RETRY_DELAY_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class FirmwareProfile:
    name: str
    idle_interval_ms: int
    idle_latency: int
    supervision_timeout_ms: int
    idle_param_fallback_delay_ms: int
    idle_param_initial_delay_ms: int = 250

    def conf_text(self) -> str:
        return "\n".join(
            (
                f"# Generated for weather BLE debug profile {self.name}",
                f"CONFIG_TXING_WEATHER_IDLE_CONN_INTERVAL_MS={self.idle_interval_ms}",
                f"CONFIG_TXING_WEATHER_IDLE_CONN_LATENCY={self.idle_latency}",
                (
                    "CONFIG_TXING_WEATHER_IDLE_CONN_SUPERVISION_TIMEOUT_MS="
                    f"{self.supervision_timeout_ms}"
                ),
                (
                    "CONFIG_TXING_WEATHER_IDLE_CONN_PARAM_FALLBACK_DELAY_MS="
                    f"{self.idle_param_fallback_delay_ms}"
                ),
                (
                    "CONFIG_TXING_WEATHER_IDLE_CONN_PARAM_INITIAL_DELAY_MS="
                    f"{self.idle_param_initial_delay_ms}"
                ),
                "",
            )
        )


PROFILES: dict[str, FirmwareProfile] = {
    profile.name: profile
    for profile in (
        FirmwareProfile("baseline-100-0-6", 100, 0, 6000, 10000),
        FirmwareProfile("stable-100-0-10", 100, 0, 10000, 10000),
        FirmwareProfile("stable-200-0-10", 200, 0, 10000, 10000),
        FirmwareProfile("stable-200-0-20", 200, 0, 20000, 10000),
        FirmwareProfile("stable-400-0-20", 400, 0, 20000, 10000),
        FirmwareProfile("fast-50-0-10", 50, 0, 10000, 10000),
        FirmwareProfile("fast-50-0-6", 50, 0, 6000, 10000),
    )
}


def load_nrf_bm_module():
    spec = importlib.util.spec_from_file_location(
        "txing_nrf_bm_toolchain",
        NRF_BM_TOOLCHAIN_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"failed to load {NRF_BM_TOOLCHAIN_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_nrf_bm_module(module) -> None:
    module.WEATHER_MCU_DIR = PRODUCTION_WEATHER_MCU_DIR
    module.WEATHER_BAREMETAL_DIR = FIRMWARE_DIR
    module.WEATHER_BUILD_DIR = BUILD_DIR
    module.WEATHER_APP_HEX = BUILD_DIR / "firmware" / "zephyr" / "zephyr.hex"
    module.WEATHER_APP_ELF = BUILD_DIR / "firmware" / "zephyr" / "zephyr.elf"
    module.WEATHER_FACTORY_HEX = BUILD_DIR / "txing_weather_ble_debug_factory.hex"
    module.OPENOCD_CFG = PRODUCTION_WEATHER_MCU_DIR / "support" / "openocd-nrf54l-cmsis-dap.cfg"
    module.BUILD_RECIPE_STAMP = BUILD_DIR / ".txing-nrf-bm-weather-ble-debug-build-recipe"


def openocd_board_support_dir(module) -> Path:
    return module.ZEPHYR_BASE / "boards" / "seeed" / "xiao_nrf54l15" / "support"


def openocd_cfg_file(module) -> Path:
    return openocd_board_support_dir(module) / "openocd.cfg"


def openocd_script_args(module) -> list[str]:
    args = ["-s", str(openocd_board_support_dir(module))]
    configured_scripts = os.environ.get("OPENOCD_SCRIPTS")
    if configured_scripts:
        return args + ["-s", configured_scripts]

    for scripts_dir in (
        Path("/opt/homebrew/share/openocd/scripts"),
        Path("/usr/local/share/openocd/scripts"),
    ):
        if (scripts_dir / "interface" / "cmsis-dap.cfg").exists():
            return args + ["-s", str(scripts_dir)]
    return args


def tcl_braced_path(module, path: Path) -> str:
    if "}" in str(path):
        module.fail(f"cannot pass path containing '}}' to OpenOCD Tcl command: {path}")
    return "{" + str(path) + "}"


def tcl_braced_literal(module, value: str, *, name: str) -> str:
    if "}" in value:
        module.fail(f"cannot pass {name} containing '}}' to OpenOCD Tcl command: {value!r}")
    return "{" + value + "}"


def openocd_adapter_args(module) -> list[str]:
    serial = os.environ.get("OPENOCD_ADAPTER_SERIAL") or os.environ.get("OPENOCD_SERIAL")
    if not serial:
        return []
    return ["-c", f"adapter serial {tcl_braced_literal(module, serial, name='adapter serial')}"]


def openocd_load_command(module, path: Path) -> str:
    return (
        f"if {{[catch {{txing-nrf54l-load {tcl_braced_path(module, path)}}} result]}} {{ "
        'echo [format "RRAMC ACCESSERRORADDR: 0x%08x" [lindex [read_memory 0x5004b408 32 1] 0]]; '
        'echo [format "RRAMC CONFIG: 0x%08x" [lindex [read_memory 0x5004b500 32 1] 0]]; '
        'echo [format "RRAMC BUFSTATUS: 0x%08x" [lindex [read_memory 0x5004b410 32 1] 0]]; '
        "error $result "
        "}"
    )


def openocd_rramc_helpers(*, rramc_config: str, erase_all: bool) -> str:
    erase_proc = (
        "proc txing-nrf54l-eraseall {} { "
        "mww 0x5004b540 0x1; "
        "sleep 100; "
        "txing-nrf54l-wait-ready eraseall "
        "}; "
        if erase_all
        else ""
    )
    erase_call = "txing-nrf54l-eraseall; " if erase_all else ""
    return (
        "proc txing-nrf54l-wait-ready {stage} { "
        "mww 0x5004b000 0x1; "
        "set timeout 2000; "
        "while {$timeout > 0} { "
        "set ready [lindex [read_memory 0x5004b400 32 1] 0]; "
        "if {[expr {$ready & 0x1}] != 0} { return }; "
        "sleep 10; "
        "incr timeout -1 "
        "}; "
        'error "RRAMC not ready during $stage" '
        "}; "
        f"{erase_proc}"
        "proc txing-nrf54l-load {file} { "
        "txing-nrf54l-wait-ready before-load; "
        f"{erase_call}"
        f"mww 0x5004b500 {rramc_config}; "
        "set txing_load_status [catch { load_image $file } txing_load_error]; "
        "mww 0x5004b500 0x0; "
        "txing-nrf54l-wait-ready after-load; "
        "if {$txing_load_status} { error $txing_load_error } "
        "}"
    )


def merge_flash_hex(module, paths: list[Path], *, label: str) -> Path:
    from intelhex import IntelHex

    path = BUILD_DIR / f"txing_weather_ble_debug_{label}.hex"
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = IntelHex()
    for source_path in paths:
        if not source_path.exists():
            module.fail(f"missing flash image: {source_path}")
        source = IntelHex(str(source_path))
        # The S115 and app HEX files can carry different start-address records.
        # They are irrelevant for OpenOCD data programming and prevent merging.
        source.start_addr = None
        merged.merge(source, overlap="error")
    merged.start_addr = None
    merged.write_hex_file(str(path))
    return path


def flash_openocd_fast(module, paths: list[Path], *, erase_all: bool, label: str) -> None:
    module.verify_local_install()
    openocd_name = os.environ.get("OPENOCD", "openocd")
    openocd = shutil.which(openocd_name) if os.path.sep not in openocd_name else openocd_name
    if openocd is None or not Path(openocd).exists():
        module.fail("openocd is missing; install it manually with Homebrew before flashing")

    cfg_file = openocd_cfg_file(module)
    if not cfg_file.exists():
        module.fail(f"missing XIAO nRF54L15 OpenOCD config: {cfg_file}")

    merged_hex = merge_flash_hex(module, paths, label=label)
    frequency = os.environ.get("OPENOCD_FREQUENCY", "100")
    # Same fast OpenOCD path as production weather MCU: write-enable RRAMC in
    # unbuffered mode and load the merged HEX in one OpenOCD session.
    rramc_config = os.environ.get("OPENOCD_RRAMC_CONFIG", "0x1")
    command = [
        str(openocd),
        *openocd_script_args(module),
        *openocd_adapter_args(module),
        "-f",
        str(cfg_file),
        "-c",
        openocd_rramc_helpers(rramc_config=rramc_config, erase_all=erase_all),
        "-c",
        f"adapter speed {frequency}",
        "-c",
        "init",
        "-c",
        "targets",
        "-c",
        "reset init",
        "-c",
        openocd_load_command(module, merged_hex),
        "-c",
        "reset run",
        "-c",
        "shutdown",
    ]
    run_flash_with_retries(
        module,
        label=label,
        operation=lambda: module.run(
            command,
            cwd=module.PROJECT_ROOT,
            env=module.local_env(),
            check=False,
        ),
    )


def run_flash_with_retries(module, *, label: str, operation) -> None:
    retries = env_non_negative_int(
        module,
        "WEATHER_BLE_DEBUG_FLASH_RETRIES",
        DEFAULT_FLASH_RETRIES,
    )
    delay_seconds = env_non_negative_float(
        module,
        "WEATHER_BLE_DEBUG_FLASH_RETRY_DELAY_SECONDS",
        DEFAULT_FLASH_RETRY_DELAY_SECONDS,
    )
    attempts = retries + 1
    last_failure: subprocess.CompletedProcess[str] | subprocess.CalledProcessError | None = None

    for attempt in range(1, attempts + 1):
        module.log(f"flash attempt {attempt}/{attempts} label={label}")
        try:
            result = operation()
        except subprocess.CalledProcessError as error:
            last_failure = error
            exit_code = error.returncode
        else:
            if result is None or result.returncode == 0:
                module.log(f"flash succeeded label={label} attempts={attempt}")
                return
            last_failure = result
            exit_code = result.returncode

        if attempt < attempts:
            module.log(
                "flash retry "
                f"{attempt}/{retries} label={label} exit={exit_code} "
                f"nextDelaySec={delay_seconds:g}"
            )
            if delay_seconds > 0:
                time.sleep(delay_seconds)

    module.log(f"flash failed label={label} attempts={attempts}")
    if isinstance(last_failure, subprocess.CompletedProcess):
        last_failure.check_returncode()
    if isinstance(last_failure, subprocess.CalledProcessError):
        raise last_failure
    module.fail(f"flash failed label={label} without a subprocess result")


def env_non_negative_int(module, name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        module.fail(f"{name} must be an integer, got {raw!r}")
    if value < 0:
        module.fail(f"{name} must be non-negative, got {value}")
    return value


def env_non_negative_float(module, name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        module.fail(f"{name} must be a number, got {raw!r}")
    if value < 0:
        module.fail(f"{name} must be non-negative, got {value}")
    return value


def verify_openocd_fast(module, paths: list[Path], *, label: str) -> None:
    module.verify_local_install()
    openocd_name = os.environ.get("OPENOCD", "openocd")
    openocd = shutil.which(openocd_name) if os.path.sep not in openocd_name else openocd_name
    if openocd is None or not Path(openocd).exists():
        module.fail("openocd is missing; install it manually with Homebrew before verifying")

    cfg_file = openocd_cfg_file(module)
    if not cfg_file.exists():
        module.fail(f"missing XIAO nRF54L15 OpenOCD config: {cfg_file}")

    merged_hex = merge_flash_hex(module, paths, label=label)
    frequency = os.environ.get("OPENOCD_FREQUENCY", "100")
    module.run(
        [
            str(openocd),
            *openocd_script_args(module),
            *openocd_adapter_args(module),
            "-f",
            str(cfg_file),
            "-c",
            f"adapter speed {frequency}",
            "-c",
            "init",
            "-c",
            "targets",
            "-c",
            "reset halt",
            "-c",
            f"verify_image {tcl_braced_path(module, merged_hex)}",
            "-c",
            "shutdown",
        ],
        cwd=module.PROJECT_ROOT,
        env=module.local_env(),
    )


def write_profile_conf(profile: FirmwareProfile) -> Path:
    path = GENERATED_DIR / f"{profile.name}.conf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.conf_text(), encoding="utf-8")
    return path


def build_recipe_stamp(module, profile: FirmwareProfile) -> str:
    return "\n".join(
        (
            f"nrf_bm={module.BM_VERSION}",
            f"sdk={module.SDK_VERSION}",
            f"board={module.WEATHER_BOARD}",
            f"app={module.WEATHER_BAREMETAL_DIR.relative_to(module.PROJECT_ROOT)}",
            f"profile={profile.name}",
            f"idle_interval_ms={profile.idle_interval_ms}",
            f"idle_latency={profile.idle_latency}",
            f"supervision_timeout_ms={profile.supervision_timeout_ms}",
            f"idle_param_fallback_delay_ms={profile.idle_param_fallback_delay_ms}",
            f"idle_param_initial_delay_ms={profile.idle_param_initial_delay_ms}",
            f"weather_baremetal_sha256={module.weather_recipe_digest()}",
            "",
        )
    )


def build_is_current(module, profile: FirmwareProfile) -> bool:
    if not (module.WEATHER_BUILD_DIR / "CMakeCache.txt").exists():
        return False
    if not (module.WEATHER_BUILD_DIR / "build.ninja").exists():
        return False
    stamp = build_recipe_stamp(module, profile)
    return module.BUILD_RECIPE_STAMP.exists() and module.BUILD_RECIPE_STAMP.read_text(
        encoding="utf-8"
    ) == stamp


def build_debug_firmware(module, profile: FirmwareProfile, *, pristine: bool) -> None:
    module.verify_local_install()
    profile_conf = write_profile_conf(profile)
    if pristine or not build_is_current(module, profile):
        pristine_mode = "always" if pristine or module.WEATHER_BUILD_DIR.exists() else "never"
        module.run(
            module.west_command()
            + [
                "build",
                "-p",
                pristine_mode,
                "-b",
                module.WEATHER_BOARD,
                str(module.WEATHER_BAREMETAL_DIR),
                "-d",
                str(module.WEATHER_BUILD_DIR),
                "--",
                "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE",
                f"-Dfirmware_EXTRA_CONF_FILE={profile_conf}",
            ],
            cwd=module.WORKSPACE_DIR,
            env=module.local_env(),
        )
    else:
        module.run(
            module.west_command() + ["build", "-d", str(module.WEATHER_BUILD_DIR)],
            cwd=module.WORKSPACE_DIR,
            env=module.local_env(),
        )

    if not module.WEATHER_APP_HEX.exists():
        module.fail(
            "build completed, but no expected application HEX was created: "
            f"{module.WEATHER_APP_HEX}"
        )
    if not module.WEATHER_APP_ELF.exists():
        module.fail(
            "build completed, but no expected application ELF was created: "
            f"{module.WEATHER_APP_ELF}"
        )
    module.ensure_app_does_not_overlap_factory()
    module.softdevice_hex()
    module.BUILD_RECIPE_STAMP.write_text(build_recipe_stamp(module, profile), encoding="utf-8")
    module.log(f"ok: built profile={profile.name} app={module.WEATHER_APP_HEX}")


def install(module, profile: FirmwareProfile) -> None:
    module.check_host_tools()
    module.ensure_dirs()
    module.ensure_workspace()
    module.install_python_requirements()
    module.ensure_sdk_toolchain()
    build_debug_firmware(module, profile, pristine=True)


def check(module, profile: FirmwareProfile) -> None:
    module.check_host_tools()
    module.verify_local_install()
    module.install_python_requirements()
    build_debug_firmware(module, profile, pristine=False)


def flash_nve(module, thing_name: str) -> None:
    factory_hex = module.write_factory_hex(thing_name)
    flash_openocd_fast(module, [factory_hex], erase_all=False, label="nve")


def verify_nve(module, thing_name: str) -> None:
    factory_hex = module.write_factory_hex(thing_name)
    verify_openocd_fast(module, [factory_hex], label="nve")


def flash_softdevice(module) -> None:
    flash_openocd_fast(
        module,
        [module.softdevice_hex()],
        erase_all=False,
        label="softdevice",
    )


def verify_softdevice(module) -> None:
    verify_openocd_fast(module, [module.softdevice_hex()], label="softdevice")


def verify_app_flash(module, profile: FirmwareProfile) -> None:
    build_debug_firmware(module, profile, pristine=False)
    verify_openocd_fast(module, [module.WEATHER_APP_HEX], label="app_flash")


def print_profiles() -> None:
    for profile in PROFILES.values():
        print(
            " ".join(
                (
                    profile.name,
                    f"idle_interval_ms={profile.idle_interval_ms}",
                    f"idle_latency={profile.idle_latency}",
                    f"supervision_timeout_ms={profile.supervision_timeout_ms}",
                    f"idle_param_fallback_delay_ms={profile.idle_param_fallback_delay_ms}",
                    f"idle_param_initial_delay_ms={profile.idle_param_initial_delay_ms}",
                )
            )
        )


def print_paths(module, profile: FirmwareProfile) -> None:
    print(f"nrf_bm_root={module.NRF_BM_DIR}")
    print(f"workspace={module.WORKSPACE_DIR}")
    print(f"zephyr_base={module.ZEPHYR_BASE}")
    print(f"zephyr_sdk={module.SDK_DIR}")
    print(f"weather_build={module.WEATHER_BUILD_DIR}")
    print(f"weather_app_hex={module.WEATHER_APP_HEX}")
    print(f"weather_app_elf={module.WEATHER_APP_ELF}")
    print(f"weather_factory_hex={module.WEATHER_FACTORY_HEX}")
    print(f"weather_factory_address=0x{module.FACTORY_DATA_ADDRESS:08x}")
    print(f"weather_rtt_ram=0x{module.RTT_RAM_START:08x}+0x{module.RTT_RAM_SIZE:x}")
    print(f"weather_rtt_port={module.RTT_PORT}")
    print(f"softdevice_hex={module.softdevice_hex() if module.BM_MANIFEST_DIR.exists() else ''}")
    print(f"openocd_cfg={openocd_cfg_file(module)}")
    print(f"weather_profile={profile.name}")
    print(f"weather_profile_conf={GENERATED_DIR / (profile.name + '.conf')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and manually flash the weather BLE debug S115 bare-metal firmware."
    )
    parser.add_argument(
        "command",
        choices=(
            "install",
            "check",
            "build",
            "flash-app",
            "flash-softdevice",
            "flash-nve",
            "verify-app",
            "verify-softdevice",
            "verify-nve",
            "rtt",
            "paths",
            "profiles",
        ),
    )
    parser.add_argument("thing_name", nargs="?")
    parser.add_argument("--profile", choices=tuple(PROFILES), default=DEFAULT_PROFILE)
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    module = load_nrf_bm_module()
    configure_nrf_bm_module(module)

    if args.command == "install":
        install(module, profile)
    elif args.command == "check":
        check(module, profile)
    elif args.command == "build":
        build_debug_firmware(module, profile, pristine=False)
    elif args.command == "flash-app":
        build_debug_firmware(module, profile, pristine=False)
        flash_openocd_fast(
            module,
            [module.WEATHER_APP_HEX],
            erase_all=False,
            label="app_flash",
        )
    elif args.command == "flash-softdevice":
        flash_softdevice(module)
    elif args.command == "flash-nve":
        if not args.thing_name:
            module.fail("flash-nve requires a weather Thing ID")
        flash_nve(module, args.thing_name)
    elif args.command == "verify-app":
        verify_app_flash(module, profile)
    elif args.command == "verify-softdevice":
        verify_softdevice(module)
    elif args.command == "verify-nve":
        if not args.thing_name:
            module.fail("verify-nve requires a weather Thing ID")
        verify_nve(module, args.thing_name)
    elif args.command == "rtt":
        module.start_weather_rtt_server()
    elif args.command == "profiles":
        print_profiles()
    else:
        print_paths(module, profile)


if __name__ == "__main__":
    main()
