#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import shlex
import subprocess
import venv
from pathlib import Path


MCU_DIR = Path(__file__).resolve().parents[1]
DEVICE_DIR = MCU_DIR.parent
PROJECT_ROOT = MCU_DIR.parents[2]
COMMON_MCU_DIR = PROJECT_ROOT / "devices" / "common" / "mcu"

VENV_DIR = MCU_DIR / ".venv"
PIP_CACHE_DIR = MCU_DIR / ".pip-cache"
ZEPHYR_CACHE_DIR = MCU_DIR / ".zephyr-cache"
CCACHE_DIR = MCU_DIR / ".ccache"

ZEPHYR_BASE = COMMON_MCU_DIR / "zephyr"
SEEED_PLATFORM = COMMON_MCU_DIR / "seeed-platform"
BOARD_ROOT = SEEED_PLATFORM / "zephyr"
BOARD_DIR = BOARD_ROOT / "boards" / "arm" / "xiao_nrf54l15"
OPENOCD_SUPPORT_DIR = BOARD_DIR / "support"
OPENOCD_CFG = OPENOCD_SUPPORT_DIR / "openocd.cfg"

BOARD = "xiao_nrf54l15/nrf54l15/cpuapp"
BUILD_VERSION = "zephyr-v40201-homebrew"
CONFIG_PATH = MCU_DIR / "conf" / "mcu.yaml"
BUILD_DIR = MCU_DIR / "build" / "zephyr-xiao_nrf54l15_cpuapp-brew"
FIRMWARE_ELF = BUILD_DIR / "zephyr" / "zephyr.elf"
FIRMWARE_HEX = BUILD_DIR / "zephyr" / "zephyr.hex"
GENERATED_CONF = BUILD_DIR / "power-generated.conf"

REQUIRED_CONFIG_FIELDS = (
    "deviceName",
    "advInterval",
    "advTxPowerDbm",
    "advConnectable",
    "advScannable",
    "advIncludeUuid",
    "gatt",
    "redconConnIntervalMs",
    "redconConnLatency",
    "redconConnSupervisionMs",
    "redconStateNotifyIntervalSeconds",
    "redconIdleDisconnectDelayMs",
    "redconBatteryAdcSettleMs",
)
_CONFIG_CACHE: dict[str, object] | None = None

SUBMODULE_PATHS = [
    COMMON_MCU_DIR / "zephyr",
    COMMON_MCU_DIR / "seeed-platform",
    COMMON_MCU_DIR / "modules" / "hal" / "nordic",
    COMMON_MCU_DIR / "modules" / "hal" / "cmsis",
    COMMON_MCU_DIR / "modules" / "hal" / "cmsis_6",
    COMMON_MCU_DIR / "modules" / "lib" / "picolibc",
]
ZEPHYR_MODULES = [
    COMMON_MCU_DIR / "modules" / "hal" / "cmsis",
    COMMON_MCU_DIR / "modules" / "hal" / "cmsis_6",
    COMMON_MCU_DIR / "modules" / "hal" / "nordic",
    COMMON_MCU_DIR / "modules" / "lib" / "picolibc",
]


def parse_yaml_scalar(raw: str) -> object:
    value = raw.strip()
    if (
        (len(value) >= 2)
        and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'"))
    ):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def split_yaml_key_value(text: str, line_number: int) -> tuple[str, object]:
    if ":" not in text:
        raise SystemExit(f"{CONFIG_PATH}:{line_number}: expected key: value")
    key, raw_value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise SystemExit(f"{CONFIG_PATH}:{line_number}: empty key")
    return key, parse_yaml_scalar(raw_value)


def load_raw_mcu_config() -> dict[str, object]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"missing power MCU config: {CONFIG_PATH}")

    config: dict[str, object] = {}
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if line.startswith("\t"):
                raise SystemExit(f"{CONFIG_PATH}:{line_number}: use spaces, not tabs")
            if line.startswith(" "):
                raise SystemExit(
                    f"{CONFIG_PATH}:{line_number}: single config uses only top-level keys"
                )
            key, value = split_yaml_key_value(line.strip(), line_number)
            if key in config:
                raise SystemExit(f"{CONFIG_PATH}:{line_number}: duplicate key {key!r}")
            config[key] = value
    return config


def require_string(config: dict[str, object], key: str) -> str:
    value = config[key]
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{CONFIG_PATH}: {key} must be a non-empty string")
    return value.strip()


def require_int(config: dict[str, object], key: str, *, base: int = 10) -> int:
    value = config[key]
    if isinstance(value, bool):
        raise SystemExit(f"{CONFIG_PATH}: {key} must be an integer")
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip(), base)
    except ValueError as err:
        raise SystemExit(f"{CONFIG_PATH}: {key} must be an integer") from err


def require_bool(config: dict[str, object], key: str) -> bool:
    value = config[key]
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"{CONFIG_PATH}: {key} must be a boolean")


def load_mcu_config() -> dict[str, object]:
    global _CONFIG_CACHE

    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    raw_config = load_raw_mcu_config()
    missing = [field for field in REQUIRED_CONFIG_FIELDS if field not in raw_config]
    if missing:
        raise SystemExit(f"{CONFIG_PATH}: missing fields: {', '.join(missing)}")

    unknown = sorted(set(raw_config) - set(REQUIRED_CONFIG_FIELDS))
    if unknown:
        raise SystemExit(f"{CONFIG_PATH}: unknown fields: {', '.join(unknown)}")

    config: dict[str, object] = {
        "deviceName": require_string(raw_config, "deviceName"),
        "advInterval": require_string(raw_config, "advInterval"),
        "advTxPowerDbm": require_int(raw_config, "advTxPowerDbm"),
        "advConnectable": require_bool(raw_config, "advConnectable"),
        "advScannable": require_bool(raw_config, "advScannable"),
        "advIncludeUuid": require_bool(raw_config, "advIncludeUuid"),
        "gatt": require_bool(raw_config, "gatt"),
        "redconConnIntervalMs": require_int(raw_config, "redconConnIntervalMs"),
        "redconConnLatency": require_int(raw_config, "redconConnLatency"),
        "redconConnSupervisionMs": require_int(raw_config, "redconConnSupervisionMs"),
        "redconStateNotifyIntervalSeconds": require_int(
            raw_config, "redconStateNotifyIntervalSeconds"
        ),
        "redconIdleDisconnectDelayMs": require_int(raw_config, "redconIdleDisconnectDelayMs"),
        "redconBatteryAdcSettleMs": require_int(raw_config, "redconBatteryAdcSettleMs"),
    }

    try:
        int(str(config["advInterval"]).strip(), 0)
    except ValueError as err:
        raise SystemExit(f"{CONFIG_PATH}: advInterval must be an integer literal") from err

    if config["advIncludeUuid"] and not config["advScannable"]:
        raise SystemExit(f"{CONFIG_PATH}: advIncludeUuid requires advScannable")
    if config["gatt"] and not config["advConnectable"]:
        raise SystemExit(f"{CONFIG_PATH}: gatt requires advConnectable")
    if config["gatt"] and not config["advIncludeUuid"]:
        raise SystemExit(f"{CONFIG_PATH}: gatt requires advIncludeUuid")
    validate_redcon_timing_config(config)

    _CONFIG_CACHE = config
    return config


def validate_range(config: dict[str, object], key: str, low: int, high: int) -> None:
    value = config[key]
    if not isinstance(value, int) or value < low or value > high:
        raise SystemExit(f"{CONFIG_PATH}: {key} must be {low}..{high}")


def validate_redcon_timing_config(config: dict[str, object]) -> None:
    validate_range(config, "redconConnIntervalMs", 8, 4000)
    validate_range(config, "redconConnLatency", 0, 499)
    validate_range(config, "redconConnSupervisionMs", 100, 32000)
    validate_range(config, "redconStateNotifyIntervalSeconds", 1, 3600)
    validate_range(config, "redconIdleDisconnectDelayMs", 0, 60000)
    validate_range(config, "redconBatteryAdcSettleMs", 0, 60000)

    minimum_supervision_ms = (
        int(config["redconConnIntervalMs"])
        * (int(config["redconConnLatency"]) + 1)
        * 2
    )
    if int(config["redconConnSupervisionMs"]) <= minimum_supervision_ms:
        raise SystemExit(
            f"{CONFIG_PATH}: redconConnSupervisionMs must be greater than "
            "redconConnIntervalMs * (redconConnLatency + 1) * 2"
        )


def cmake_bool(value: object) -> str:
    return "1" if value else "0"


def build_dir() -> Path:
    return BUILD_DIR


def firmware_elf() -> Path:
    return FIRMWARE_ELF


def firmware_hex() -> Path:
    return FIRMWARE_HEX


def python_executable() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def cross_compile_prefix() -> str:
    configured = (
        os.environ.get("POWER_MCU_CROSS_COMPILE")
        or os.environ.get("POWER_CROSS_COMPILE")
        or os.environ.get("CROSS_COMPILE")
    )
    if configured:
        return configured

    for prefix in (
        "/opt/homebrew/bin/arm-none-eabi-",
        "/usr/local/bin/arm-none-eabi-",
    ):
        if Path(prefix + "gcc").exists():
            return prefix

    gcc = shutil.which("arm-none-eabi-gcc")
    if gcc:
        return str(Path(gcc).with_name("arm-none-eabi-"))

    return "/opt/homebrew/bin/arm-none-eabi-"


def tool_path(name: str) -> Path:
    return Path(cross_compile_prefix() + name)


def openocd_executable() -> str:
    openocd = "openocd"
    if shutil.which(openocd) is None:
        raise SystemExit(
            "missing OpenOCD for power flash.\n"
            "Install manually with:\n"
            "  brew install open-ocd\n"
            "Then ensure openocd is available in PATH."
        )
    return openocd


def command_env() -> dict[str, str]:
    local = os.environ.copy()
    prefix = cross_compile_prefix()
    path_entries = [
        str(python_executable().parent),
        str(Path(prefix + "gcc").parent),
        local.get("PATH", ""),
    ]
    local["PIP_CACHE_DIR"] = str(PIP_CACHE_DIR)
    local["POWER_BOARD_ROOT"] = str(BOARD_ROOT)
    local["CCACHE_DIR"] = str(CCACHE_DIR)
    local["CCACHE_DISABLE"] = "1"
    local["ZEPHYR_CACHE_DIR"] = str(ZEPHYR_CACHE_DIR)
    local["ZEPHYR_BASE"] = str(ZEPHYR_BASE)
    local["ZEPHYR_TOOLCHAIN_VARIANT"] = "cross-compile"
    local["CROSS_COMPILE"] = prefix
    local.pop("GNUARMEMB_TOOLCHAIN_PATH", None)
    local["PATH"] = os.pathsep.join(part for part in path_entries if part)
    return local


def run(
    args: list[str | Path],
    *,
    cwd: Path = MCU_DIR,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [str(arg) for arg in args]
    print(
        "+ (" + str(cwd) + ") " + " ".join(shlex.quote(part) for part in command),
        flush=True,
    )
    return subprocess.run(
        command,
        cwd=cwd,
        env=command_env(),
        text=True,
        check=check,
        capture_output=capture_output,
    )


def ensure_submodules_present() -> None:
    missing = [
        path
        for path in SUBMODULE_PATHS
        if not path.exists() or not any(path.iterdir())
    ]
    if missing:
        paths = "\n".join(f"  - {path}" for path in missing)
        raise SystemExit(
            "missing power Zephyr submodules. Run:\n"
            "  just power::mcu::submodules\n"
            "Missing paths:\n"
            f"{paths}"
        )


def submodules() -> None:
    run(
        [
            "git",
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--",
            *(str(path.relative_to(PROJECT_ROOT)) for path in SUBMODULE_PATHS),
        ],
        cwd=PROJECT_ROOT,
    )


def ensure_python_environment() -> None:
    if not python_executable().exists():
        raise SystemExit(
            "missing power Python environment. Run: "
            "just power::mcu::install"
        )


def ensure_toolchain() -> None:
    prefix = cross_compile_prefix()
    gcc = Path(prefix + "gcc")
    ld_bfd = Path(prefix + "ld.bfd")
    ld = Path(prefix + "ld")
    objcopy = Path(prefix + "objcopy")
    size = Path(prefix + "size")

    missing = [path for path in (gcc, objcopy, size) if not path.exists()]
    if not ld_bfd.exists() and not ld.exists():
        missing.append(ld_bfd)
    if missing:
        paths = "\n".join(f"  - {path}" for path in missing)
        raise SystemExit(
            "missing Homebrew arm-none-eabi toolchain binaries.\n"
            "Install manually with:\n"
            "  brew install arm-none-eabi-gcc arm-none-eabi-binutils\n"
            "Or set POWER_MCU_CROSS_COMPILE to a full prefix such as "
            "/opt/homebrew/bin/arm-none-eabi-\n"
            "Missing:\n"
            f"{paths}"
        )

    result = subprocess.run(
        [str(gcc), "--version"],
        cwd=MCU_DIR,
        env=command_env(),
        text=True,
        check=False,
        capture_output=True,
    )
    first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
    if "arm-none-eabi-gcc" not in first_line:
        raise SystemExit(
            "unexpected compiler version output from "
            f"{gcc}: {first_line or 'unknown'}"
        )


def install() -> None:
    ensure_submodules_present()
    PIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ZEPHYR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CCACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not python_executable().exists():
        print(f"creating power Zephyr venv: {VENV_DIR}", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    run(
        [
            python_executable(),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "-r",
            ZEPHYR_BASE / "scripts" / "requirements-base.txt",
        ],
    )
    run([python_executable(), "-m", "west", "--version"])
    ensure_toolchain()


def ensure_ready() -> None:
    ensure_python_environment()
    ensure_submodules_present()
    ensure_toolchain()


def kconfig_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_generated_config(config: dict[str, object]) -> None:
    GENERATED_CONF.parent.mkdir(parents=True, exist_ok=True)
    content = f'CONFIG_BT_DEVICE_NAME="{kconfig_quote(str(config["deviceName"]))}"\n'
    if not GENERATED_CONF.exists() or GENERATED_CONF.read_text(encoding="utf-8") != content:
        GENERATED_CONF.write_text(content, encoding="utf-8")


def configure() -> None:
    ensure_ready()
    config = load_mcu_config()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    write_generated_config(config)
    module_arg = ";".join(str(path) for path in ZEPHYR_MODULES)
    conf_files = [MCU_DIR / "zephyr" / "prj.conf", GENERATED_CONF]
    if config["gatt"]:
        conf_files.append(MCU_DIR / "zephyr" / "prj-gatt.conf")
    conf_file_arg = ";".join(str(path) for path in conf_files)
    run(
        [
            "cmake",
            "-S",
            MCU_DIR / "zephyr",
            "-B",
            BUILD_DIR,
            "-G",
            "Ninja",
            f"-DBOARD={BOARD}",
            f"-DBOARD_ROOT={BOARD_ROOT}",
            f"-DZEPHYR_MODULES={module_arg}",
            f"-DPython3_EXECUTABLE={python_executable()}",
            f"-DPYTHON_EXECUTABLE={python_executable()}",
            f"-DGEN_KOBJECT_LIST={ZEPHYR_BASE / 'scripts' / 'build' / 'gen_kobject_list.py'}",
            f"-DBUILD_VERSION={BUILD_VERSION}",
            f"-DUSER_CACHE_DIR={ZEPHYR_CACHE_DIR}",
            f"-DCONF_FILE={conf_file_arg}",
            f"-DPOWER_ADV_INTERVAL={config['advInterval']}",
            f"-DPOWER_ADV_TX_POWER_DBM={config['advTxPowerDbm']}",
            f"-DPOWER_ADV_CONNECTABLE={cmake_bool(config['advConnectable'])}",
            f"-DPOWER_ADV_SCANNABLE={cmake_bool(config['advScannable'])}",
            f"-DPOWER_ADV_INCLUDE_UUID={cmake_bool(config['advIncludeUuid'])}",
            f"-DPOWER_GATT={cmake_bool(config['gatt'])}",
            f"-DPOWER_REDCON_CONN_INTERVAL_MS={config['redconConnIntervalMs']}",
            f"-DPOWER_REDCON_CONN_LATENCY={config['redconConnLatency']}",
            f"-DPOWER_REDCON_CONN_SUPERVISION_MS={config['redconConnSupervisionMs']}",
            f"-DPOWER_REDCON_STATE_NOTIFY_INTERVAL_SECONDS={config['redconStateNotifyIntervalSeconds']}",
            f"-DPOWER_REDCON_IDLE_DISCONNECT_DELAY_MS={config['redconIdleDisconnectDelayMs']}",
            f"-DPOWER_REDCON_BATTERY_ADC_SETTLE_MS={config['redconBatteryAdcSettleMs']}",
            "-DZEPHYR_TOOLCHAIN_VARIANT=cross-compile",
            f"-DCROSS_COMPILE={cross_compile_prefix()}",
            "-DUSE_CCACHE=0",
            "-DCCACHE_PROGRAM=CCACHE_PROGRAM-NOTFOUND",
            "-DCMAKE_C_COMPILER_LAUNCHER=",
            "-DCMAKE_CXX_COMPILER_LAUNCHER=",
        ],
    )


def build() -> None:
    configure()
    run(["cmake", "--build", BUILD_DIR])


def flash_openocd_command() -> list[Path | str]:
    if not FIRMWARE_HEX.exists():
        raise SystemExit("missing firmware hex. Run: just power::mcu::check")
    if not OPENOCD_CFG.exists():
        raise SystemExit(f"missing Seeed OpenOCD config: {OPENOCD_CFG}")
    return [
        openocd_executable(),
        "-s",
        OPENOCD_SUPPORT_DIR,
        "-f",
        OPENOCD_CFG,
        "-c",
        "init",
        "-c",
        "targets nrf54l.cpu",
        "-c",
        "reset init",
        "-c",
        f"nrf54l-load {FIRMWARE_HEX}",
        "-c",
        f"verify_image {FIRMWARE_HEX}",
        "-c",
        "reset run",
        "-c",
        "shutdown",
    ]


def flash() -> None:
    run(flash_openocd_command())


def flash_check() -> None:
    ensure_ready()
    command = [str(part) for part in flash_openocd_command()]
    print(" ".join(shlex.quote(part) for part in command))


def clean() -> None:
    if BUILD_DIR.exists():
        print(f"removing {BUILD_DIR}", flush=True)
        shutil.rmtree(BUILD_DIR)


def print_path(label: str, path: Path) -> None:
    print(f"{label}: {path} exists={int(path.exists())}")


def paths() -> None:
    config = load_mcu_config()
    print(f"projectRoot: {PROJECT_ROOT}")
    print(f"deviceDir: {DEVICE_DIR}")
    print(f"mcuDir: {MCU_DIR}")
    print(f"board: {BOARD}")
    print(f"buildVersion: {BUILD_VERSION}")
    print(f"config: {CONFIG_PATH}")
    print(f"deviceName: {config['deviceName']}")
    print(f"advInterval: {config['advInterval']}")
    print(f"advTxPowerDbm: {config['advTxPowerDbm']}")
    print(f"advConnectable: {cmake_bool(config['advConnectable'])}")
    print(f"advScannable: {cmake_bool(config['advScannable'])}")
    print(f"advIncludeUuid: {cmake_bool(config['advIncludeUuid'])}")
    print(f"gatt: {cmake_bool(config['gatt'])}")
    print(f"redconConnIntervalMs: {config['redconConnIntervalMs']}")
    print(f"redconConnLatency: {config['redconConnLatency']}")
    print(f"redconConnSupervisionMs: {config['redconConnSupervisionMs']}")
    print(f"redconStateNotifyIntervalSeconds: {config['redconStateNotifyIntervalSeconds']}")
    print(f"redconIdleDisconnectDelayMs: {config['redconIdleDisconnectDelayMs']}")
    print(f"redconBatteryAdcSettleMs: {config['redconBatteryAdcSettleMs']}")
    print_path("venv", VENV_DIR)
    print_path("python", python_executable())
    print_path("pipCache", PIP_CACHE_DIR)
    print_path("zephyrCache", ZEPHYR_CACHE_DIR)
    print_path("ccache", CCACHE_DIR)
    print_path("zephyrBase", ZEPHYR_BASE)
    print_path("seeedPlatform", SEEED_PLATFORM)
    print_path("boardRoot", BOARD_ROOT)
    print_path("boardDir", BOARD_DIR)
    print_path("openocdCfg", OPENOCD_CFG)
    print_path("buildDir", build_dir())
    print_path("generatedConf", GENERATED_CONF)
    print_path("firmwareElf", firmware_elf())
    print_path("firmwareHex", firmware_hex())
    print("toolchainVariant: cross-compile")
    print(f"crossCompile: {cross_compile_prefix()}")
    print_path("gcc", tool_path("gcc"))
    print_path("ldBfd", tool_path("ld.bfd"))
    print_path("ld", tool_path("ld"))
    print_path("objcopy", tool_path("objcopy"))
    print_path("size", tool_path("size"))
    print(f"openocdCommand: {openocd_executable()}")
    print(f"openocdInPath: {shutil.which(openocd_executable())}")
    for module in ZEPHYR_MODULES:
        print_path("module", module)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build power firmware")
    parser.add_argument(
        "command",
        choices=[
            "submodules",
            "install",
            "check",
            "build",
            "flash",
            "flash-check",
            "paths",
            "clean",
        ],
    )
    args = parser.parse_args()

    if args.command == "submodules":
        submodules()
    elif args.command == "install":
        install()
    elif args.command in {"check", "build"}:
        build()
    elif args.command == "flash":
        flash()
    elif args.command == "flash-check":
        flash_check()
    elif args.command == "paths":
        paths()
    elif args.command == "clean":
        clean()


if __name__ == "__main__":
    main()
