#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import shlex
import subprocess
import sys
from pathlib import Path


ZEPHYR_VERSION = "v4.4.0"
ZEPHYR_REPO = "https://github.com/zephyrproject-rtos/zephyr"
BOARD = "xiao_nrf54l15/nrf54l15/cpuapp"
BUILD_NAME = "zephyr-xiao_nrf54l15_cpuapp"
BUILD_VERSION = "zephyr-v4.4.0"
NVE_ADDRESS = "0x000f0000"
ACTIVE_DEVICES = ("power", "weather", "unit")

PROJECT_ROOT = Path(__file__).resolve().parents[4]
COMMON_MCU_DIR = PROJECT_ROOT / "devices" / "common" / "mcu"
WORKSPACE_DIR = COMMON_MCU_DIR / "zephyr"
ZEPHYR_BASE = WORKSPACE_DIR / "zephyr"
WEST_CONFIG = WORKSPACE_DIR / ".west" / "config"
VENV_DIR = COMMON_MCU_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
WEST_BIN = VENV_DIR / "bin" / "west"
LOCAL_HOME = COMMON_MCU_DIR / ".home"
PIP_CACHE_DIR = COMMON_MCU_DIR / ".pip-cache"
ZEPHYR_CACHE_DIR = COMMON_MCU_DIR / ".zephyr-cache"
CCACHE_DIR = COMMON_MCU_DIR / ".ccache"
NVE_SCRIPT = COMMON_MCU_DIR / "xiao_nrf54l15" / "scripts" / "redcon_nve.py"
BOARD_CONF = COMMON_MCU_DIR / "xiao_nrf54l15" / "board.conf"
COMMON_BUILD_DIR = COMMON_MCU_DIR / "build"
NVE_HEX = COMMON_BUILD_DIR / "redcon-factory-nve.hex"
OPENOCD_SUPPORT_DIR = ZEPHYR_BASE / "boards" / "seeed" / "xiao_nrf54l15" / "support"
OPENOCD_CFG = OPENOCD_SUPPORT_DIR / "openocd.cfg"


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(message)


def run(
    args: list[str | Path],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    log(f"+ ({cwd}) {shlex.join(str(arg) for arg in args)}")
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def local_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(LOCAL_HOME)
    env["XDG_CACHE_HOME"] = str(LOCAL_HOME / ".cache")
    env["PIP_CACHE_DIR"] = str(PIP_CACHE_DIR)
    env["ZEPHYR_CACHE_DIR"] = str(ZEPHYR_CACHE_DIR)
    env["CCACHE_DIR"] = str(CCACHE_DIR)
    env["PATH"] = f"{VENV_DIR / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.pop("BOARD_ROOT", None)
    env.pop("POWER_BOARD_ROOT", None)
    env.pop("ZEPHYR_MODULES", None)
    env.pop("ZEPHYR_SDK_INSTALL_DIRS", None)
    env.pop("ZEPHYR_SDK_INSTALL_DIR", None)
    env.pop("CROSS_COMPILE", None)
    if not env.get("ZEPHYR_TOOLCHAIN_VARIANT"):
        env["ZEPHYR_TOOLCHAIN_VARIANT"] = "gnuarmemb"
    if env["ZEPHYR_TOOLCHAIN_VARIANT"] == "gnuarmemb" and not env.get(
        "GNUARMEMB_TOOLCHAIN_PATH"
    ):
        gcc_path = shutil.which("arm-none-eabi-gcc")
        if gcc_path:
            env["GNUARMEMB_TOOLCHAIN_PATH"] = str(Path(gcc_path).parents[1])
    return env


def ensure_dirs() -> None:
    for path in (
        COMMON_MCU_DIR,
        COMMON_BUILD_DIR,
        LOCAL_HOME,
        LOCAL_HOME / ".cache",
        PIP_CACHE_DIR,
        ZEPHYR_CACHE_DIR,
        CCACHE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def require_commands(*commands: str) -> None:
    missing = [command for command in commands if shutil.which(command) is None]
    if missing:
        fail("missing required host tool(s): " + ", ".join(missing))


def ensure_venv() -> None:
    ensure_dirs()
    if VENV_PYTHON.exists():
        completed = subprocess.run(
            [str(VENV_PYTHON), "-c", "import sys"],
            cwd=COMMON_MCU_DIR,
            env=local_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if completed.returncode != 0:
            shutil.rmtree(VENV_DIR)
    if not VENV_PYTHON.exists():
        run([sys.executable, "-m", "venv", VENV_DIR], cwd=COMMON_MCU_DIR, env=local_env())
    run(
        [VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "west"],
        cwd=COMMON_MCU_DIR,
        env=local_env(),
    )


def west_command() -> list[Path]:
    if not WEST_BIN.exists():
        fail("missing repo-local west. Run: just mcu::install")
    return [WEST_BIN]


def ensure_workspace() -> None:
    ensure_venv()
    if WORKSPACE_DIR.exists() and not WEST_CONFIG.exists():
        fail(f"refusing to use existing non-west workspace: {WORKSPACE_DIR}")
    if not WEST_CONFIG.exists():
        run(
            west_command() + ["init", "-m", ZEPHYR_REPO, "--mr", ZEPHYR_VERSION, WORKSPACE_DIR],
            cwd=COMMON_MCU_DIR,
            env=local_env(),
        )
    run(
        west_command() + ["update", "--narrow", "--fetch-opt=--filter=blob:none"],
        cwd=WORKSPACE_DIR,
        env=local_env(),
    )
    run(west_command() + ["manifest", "--validate"], cwd=WORKSPACE_DIR, env=local_env())


def install_python_requirements() -> None:
    requirements = [
        ZEPHYR_BASE / "scripts" / "requirements-base.txt",
        ZEPHYR_BASE / "scripts" / "requirements-build-test.txt",
    ]
    for requirement in requirements:
        if not requirement.exists():
            fail(f"missing Zephyr Python requirements file: {requirement}")
    args: list[str | Path] = [VENV_PYTHON, "-m", "pip", "install", "--upgrade"]
    for requirement in requirements:
        args.extend(["-r", requirement])
    run(args, cwd=COMMON_MCU_DIR, env=local_env())


def verify_workspace() -> None:
    if not WEST_CONFIG.exists():
        fail("missing stock Zephyr west workspace. Run: just mcu::install")
    if not ZEPHYR_BASE.is_dir():
        fail(f"missing stock Zephyr checkout: {ZEPHYR_BASE}. Run: just mcu::install")
    if not WEST_BIN.exists():
        fail("missing repo-local west. Run: just mcu::install")
    manifest_path = run(
        west_command() + ["config", "manifest.path"],
        cwd=WORKSPACE_DIR,
        env=local_env(),
        capture=True,
    ).stdout.strip()
    if manifest_path != "zephyr":
        fail(f"unexpected west manifest.path: {manifest_path}")
    expected = run(
        ["git", "rev-list", "-n", "1", ZEPHYR_VERSION],
        cwd=ZEPHYR_BASE,
        capture=True,
    ).stdout.strip()
    actual = run(["git", "rev-parse", "HEAD"], cwd=ZEPHYR_BASE, capture=True).stdout.strip()
    if actual != expected:
        fail(f"unexpected Zephyr checkout: {actual}; expected {ZEPHYR_VERSION} ({expected})")


def install() -> None:
    require_commands("git", "python3", "cmake", "ninja", "dtc", "arm-none-eabi-gcc")
    ensure_workspace()
    install_python_requirements()


def device_mcu_dir(device: str) -> Path:
    if device not in ACTIVE_DEVICES:
        fail(
            f"unsupported MCU device type: {device}. "
            f"Supported device types: {', '.join(ACTIVE_DEVICES)}"
        )
    path = PROJECT_ROOT / "devices" / device / "mcu"
    if not path.is_dir():
        fail(f"missing MCU directory for {device}: {path}")
    return path


def app_dir(device: str) -> Path:
    path = device_mcu_dir(device) / "zephyr"
    if not path.is_dir():
        fail(f"missing Zephyr app directory for {device}: {path}")
    return path


def prj_conf(device: str) -> Path:
    return app_dir(device) / "prj.conf"


def overlay_file(device: str) -> Path:
    return app_dir(device) / "boards" / "xiao_nrf54l15_nrf54l15_cpuapp.overlay"


def build_dir(device: str) -> Path:
    return device_mcu_dir(device) / "build" / BUILD_NAME


def firmware_candidates(device: str) -> tuple[Path, Path]:
    directory = build_dir(device)
    return (
        directory / "zephyr" / "zephyr.hex",
        directory / "zephyr" / "zephyr" / "zephyr.hex",
    )


def firmware_hex(device: str) -> Path:
    candidates = firmware_candidates(device)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def require_firmware_hex(device: str) -> Path:
    candidate = firmware_hex(device)
    if not candidate.exists():
        fail(f"missing firmware hex. Run: just {device}::mcu::build")
    return candidate


def pristine_mode(device: str) -> str:
    cache = build_dir(device) / "CMakeCache.txt"
    if not cache.exists():
        return "auto"
    text = cache.read_text(encoding="utf-8", errors="replace")
    if str(ZEPHYR_BASE) not in text:
        return "always"
    expected_gnuarmemb_path = local_env().get("GNUARMEMB_TOOLCHAIN_PATH")
    if expected_gnuarmemb_path and (
        f"GNUARMEMB_TOOLCHAIN_PATH:INTERNAL={expected_gnuarmemb_path}"
        not in text.splitlines()
    ):
        return "always"
    return "auto"


def build(device: str) -> None:
    require_commands("git", "python3", "cmake", "ninja", "dtc", "arm-none-eabi-gcc")
    verify_workspace()
    conf = prj_conf(device)
    overlay = overlay_file(device)
    for path in (conf, overlay, BOARD_CONF):
        if not path.exists():
            fail(f"missing build input: {path}")
    run(
        west_command()
        + [
            "-z",
            ZEPHYR_BASE,
            "build",
            "-p",
            pristine_mode(device),
            "-b",
            BOARD,
            app_dir(device),
            "-d",
            build_dir(device),
            "--",
            f"-DCONF_FILE={conf}",
            f"-DEXTRA_CONF_FILE={BOARD_CONF}",
            f"-DDTC_OVERLAY_FILE={overlay}",
            f"-DBUILD_VERSION={BUILD_VERSION}",
        ],
        cwd=WORKSPACE_DIR,
        env=local_env(),
    )
    hex_file = firmware_hex(device)
    if not hex_file.exists():
        fail(f"build completed, but no expected firmware HEX was created: {hex_file}")
    log(f"ok: built {hex_file}")


def clean(device: str) -> None:
    path = build_dir(device)
    if path.exists():
        log(f"removing {path}")
        shutil.rmtree(path)


def openocd_command(hex_file: Path) -> list[str | Path]:
    return [
        "openocd",
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
        f"nrf54l-load {hex_file}",
        "-c",
        f"verify_image {hex_file}",
        "-c",
        "reset run",
        "-c",
        "shutdown",
    ]


def require_openocd() -> None:
    verify_workspace()
    if not OPENOCD_CFG.exists():
        fail(f"missing stock Zephyr Seeed OpenOCD config: {OPENOCD_CFG}. Run: just mcu::install")
    if shutil.which("openocd") is None:
        fail("missing OpenOCD. Install manually with: brew install open-ocd")


def print_openocd(hex_file: Path) -> None:
    print(shlex.join(str(arg) for arg in openocd_command(hex_file)))


def run_openocd(hex_file: Path) -> None:
    require_openocd()
    run(openocd_command(hex_file), cwd=PROJECT_ROOT, env=local_env())


def check_flash(device: str) -> None:
    require_openocd()
    print_openocd(require_firmware_hex(device))


def flash(device: str) -> None:
    run_openocd(require_firmware_hex(device))


def build_nve_hex(thing_name: str) -> None:
    if not NVE_SCRIPT.exists():
        fail(f"missing REDCON NVE script: {NVE_SCRIPT}")
    COMMON_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    run(
        [
            sys.executable,
            NVE_SCRIPT,
            "write-hex",
            thing_name,
            "--address",
            NVE_ADDRESS,
            "--output",
            NVE_HEX,
        ],
        cwd=PROJECT_ROOT,
        env=local_env(),
    )


def check_nve(thing_name: str) -> None:
    require_openocd()
    build_nve_hex(thing_name)
    print_openocd(NVE_HEX)


def nve(thing_name: str) -> None:
    build_nve_hex(thing_name)
    run_openocd(NVE_HEX)


def paths(device: str | None = None) -> None:
    values: dict[str, Path | str] = {
        "projectRoot": PROJECT_ROOT,
        "commonMcuDir": COMMON_MCU_DIR,
        "workspaceDir": WORKSPACE_DIR,
        "zephyrBase": ZEPHYR_BASE,
        "zephyrVersion": ZEPHYR_VERSION,
        "venv": VENV_DIR,
        "python": VENV_PYTHON,
        "west": WEST_BIN,
        "board": BOARD,
        "buildVersion": BUILD_VERSION,
        "openocdCfg": OPENOCD_CFG,
        "nveScript": NVE_SCRIPT,
        "nveHex": NVE_HEX,
        "nveAddress": NVE_ADDRESS,
    }
    if device is not None:
        values.update(
            {
                "device": device,
                "mcuDir": device_mcu_dir(device),
                "appDir": app_dir(device),
                "prjConf": prj_conf(device),
                "overlayFile": overlay_file(device),
                "buildDir": build_dir(device),
                "firmwareHex": firmware_hex(device),
            }
        )
    for label, value in values.items():
        if isinstance(value, Path):
            print(f"{label}: {value} exists={value.exists()}")
        else:
            print(f"{label}: {value}")


def require_device(command: str, device: str | None) -> str:
    if device is None:
        fail(f"{command} requires --device <device-type>")
    return device


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage txing XIAO nRF54L15 MCU builds with shared stock Zephyr."
    )
    parser.add_argument("--device", choices=ACTIVE_DEVICES)
    parser.add_argument(
        "command",
        choices=(
            "install",
            "paths",
            "check",
            "build",
            "clean",
            "check-flash",
            "flash",
            "build-nve-hex",
            "check-nve",
            "nve",
        ),
    )
    parser.add_argument("thing_name", nargs="?", default="power-test")
    args = parser.parse_args()

    if args.command == "install":
        install()
    elif args.command == "paths":
        paths(args.device)
    elif args.command == "check":
        build(require_device(args.command, args.device))
    elif args.command == "build":
        build(require_device(args.command, args.device))
    elif args.command == "clean":
        clean(require_device(args.command, args.device))
    elif args.command == "check-flash":
        check_flash(require_device(args.command, args.device))
    elif args.command == "flash":
        flash(require_device(args.command, args.device))
    elif args.command == "build-nve-hex":
        build_nve_hex(args.thing_name)
    elif args.command == "check-nve":
        check_nve(args.thing_name)
    elif args.command == "nve":
        nve(args.thing_name)


if __name__ == "__main__":
    main()
