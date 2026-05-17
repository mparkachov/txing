#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


NCS_VERSION = "v3.3.0"
SDK_VERSION = "0.17.4"
SDK_TOOLCHAINS = ("arm-zephyr-eabi",)
BOARD = "xiao_nrf54l15/nrf54l15/cpuapp"
BUILD_NAME = "ncs-xiao_nrf54l15_cpuapp"
BUILD_VERSION = f"ncs-{NCS_VERSION}"

MCU_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MCU_DIR.parents[2]
NCS_DIR = PROJECT_ROOT / "devices" / "common" / "mcu" / "ncs"
NCS_REPO = PROJECT_ROOT / "modules" / "nrfconnect" / "sdk-nrf"
ZEPHYR_BASE = NCS_DIR / "zephyr"
SDK_PARENT_DIR = NCS_DIR / "sdk"
SDK_DIR = SDK_PARENT_DIR / f"zephyr-sdk-{SDK_VERSION}"
DOWNLOADS_DIR = NCS_DIR / "downloads"
VENV_DIR = NCS_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
LOCAL_HOME = NCS_DIR / ".home"
PIP_CACHE_DIR = NCS_DIR / ".pip-cache"
ZEPHYR_CACHE_DIR = NCS_DIR / ".zephyr-cache"
CCACHE_DIR = NCS_DIR / ".ccache"
BUILD_DIR = MCU_DIR / "build" / BUILD_NAME
BUILD_RECIPE_STAMP = BUILD_DIR / ".txing-unit-ncs-build-recipe"
APP_DIR = MCU_DIR / "zephyr"
PRJ_CONF = APP_DIR / "prj.conf"
OVERLAY_FILE = APP_DIR / "boards" / "xiao_nrf54l15_nrf54l15_cpuapp.overlay"

SDK_RELEASE_BASE = (
    f"https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v{SDK_VERSION}"
)


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(message)


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    log(f"+ ({cwd}) {' '.join(str(arg) for arg in args)}")
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def local_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(LOCAL_HOME)
    env["PIP_CACHE_DIR"] = str(PIP_CACHE_DIR)
    env["ZEPHYR_BASE"] = str(ZEPHYR_BASE)
    env["ZEPHYR_SDK_INSTALL_DIR"] = str(SDK_DIR)
    env["ZEPHYR_TOOLCHAIN_VARIANT"] = "zephyr"
    env["ZEPHYR_CACHE_DIR"] = str(ZEPHYR_CACHE_DIR)
    env["CCACHE_DIR"] = str(CCACHE_DIR)
    env["PATH"] = f"{VENV_DIR / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.pop("ZEPHYR_SDK_INSTALL_DIRS", None)
    env.pop("CROSS_COMPILE", None)
    env.pop("BOARD_ROOT", None)
    env.pop("POWER_BOARD_ROOT", None)
    env.pop("ZEPHYR_MODULES", None)
    return env


def host_os_arch() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin":
        if machine not in {"arm64", "aarch64"}:
            fail(f"unsupported macOS architecture: {machine}; expected arm64")
        return "macos", "aarch64"
    if system == "Linux":
        if machine in {"x86_64", "amd64"}:
            return "linux", "x86_64"
        if machine in {"arm64", "aarch64"}:
            return "linux", "aarch64"
    fail(f"unsupported host for Zephyr SDK archive: {system} {machine}")


def ensure_dirs() -> None:
    for path in (
        NCS_DIR,
        DOWNLOADS_DIR,
        SDK_PARENT_DIR,
        LOCAL_HOME,
        PIP_CACHE_DIR,
        ZEPHYR_CACHE_DIR,
        CCACHE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def require_commands(*commands: str) -> None:
    missing = [command for command in commands if shutil.which(command) is None]
    if missing:
        fail(
            "missing required host tool(s): "
            + ", ".join(missing)
            + "\nInstall the NCS host prerequisites manually before retrying."
        )


def ensure_submodule() -> None:
    if not (NCS_REPO / "west.yml").exists():
        fail(
            f"missing NCS sdk-nrf submodule at {NCS_REPO}\n"
            "Run: just unit::mcu::submodules"
        )
    expected = run(
        ["git", "rev-list", "-n", "1", NCS_VERSION],
        cwd=NCS_REPO,
        capture=True,
    ).stdout.strip()
    actual = run(["git", "rev-parse", "HEAD"], cwd=NCS_REPO, capture=True).stdout.strip()
    if actual != expected:
        fail(
            f"unexpected sdk-nrf checkout {actual}; expected {NCS_VERSION} ({expected}).\n"
            "Run: just unit::mcu::submodules"
        )


def ensure_venv() -> None:
    ensure_dirs()
    if not VENV_PYTHON.exists():
        log(f"creating NCS Python environment: {VENV_DIR}")
        run([sys.executable, "-m", "venv", VENV_DIR], cwd=PROJECT_ROOT)
    run(
        [VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "west"],
        cwd=NCS_DIR,
        env=local_env(),
    )


def west_command() -> list[str]:
    west = VENV_DIR / "bin" / "west"
    if not west.exists():
        fail(f"west is missing from {VENV_DIR}; run `just unit::mcu::install`")
    return [str(west)]


def ensure_workspace() -> None:
    env = local_env()
    if not (NCS_DIR / ".west").is_dir():
        run(west_command() + ["init", "-l", str(NCS_REPO)], cwd=NCS_DIR, env=env)
    else:
        manifest_path = run(
            west_command() + ["config", "manifest.path"],
            cwd=NCS_DIR,
            env=env,
            capture=True,
        ).stdout.strip()
        if manifest_path != "nrf":
            fail(f"unexpected west manifest.path={manifest_path!r}; expected 'nrf'")
    run(west_command() + ["config", "update.narrow", "true"], cwd=NCS_DIR, env=env)
    run(
        west_command() + ["update", "--narrow", "--fetch-opt=--filter=blob:none"],
        cwd=NCS_DIR,
        env=env,
    )


def install_python_requirements() -> None:
    requirements = [
        ZEPHYR_BASE / "scripts" / "requirements-base.txt",
        NCS_REPO / "scripts" / "requirements.txt",
    ]
    for requirement in requirements:
        if not requirement.exists():
            fail(f"missing NCS Python requirements file: {requirement}")
    args = [VENV_PYTHON, "-m", "pip", "install", "--upgrade"]
    for requirement in requirements:
        args.extend(["-r", str(requirement)])
    run(args, cwd=NCS_DIR, env=local_env())


def sdk_archive_name() -> str:
    os_name, arch = host_os_arch()
    return f"zephyr-sdk-{SDK_VERSION}_{os_name}-{arch}_minimal.tar.xz"


def sdk_archive_url() -> str:
    return f"{SDK_RELEASE_BASE}/{sdk_archive_name()}"


def sha256_sum_url() -> str:
    return f"{SDK_RELEASE_BASE}/sha256.sum"


def download_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url) as response:
        return response.read()


def expected_sha256(filename: str) -> str:
    content = download_bytes(sha256_sum_url()).decode("utf-8")
    for line in content.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == filename:
            return parts[0]
    fail(f"could not find {filename} in Zephyr SDK sha256.sum")


def ensure_downloaded_sdk_archive() -> Path:
    ensure_dirs()
    archive = DOWNLOADS_DIR / sdk_archive_name()
    sha_path = archive.with_suffix(archive.suffix + ".sha256")
    expected = expected_sha256(archive.name)
    if archive.exists():
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest == expected:
            log(f"ok: Zephyr SDK archive already downloaded: {archive}")
            return archive
        log(f"removing Zephyr SDK archive with mismatched sha256: {archive}")
        archive.unlink()
    url = sdk_archive_url()
    log(f"downloading {url}")
    data = download_bytes(url)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        fail(f"Zephyr SDK archive sha256 mismatch: expected {expected}, got {digest}")
    archive.write_bytes(data)
    sha_path.write_text(f"{expected}  {archive.name}\n", encoding="ascii")
    return archive


def extract_tar_safely(archive: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    with tarfile.open(archive, "r:xz") as tar:
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination_root):
                fail(f"refusing to extract archive member outside destination: {member.name}")
        tar.extractall(destination)


def ensure_sdk_extracted() -> None:
    if (SDK_DIR / "setup.sh").exists():
        return
    archive = ensure_downloaded_sdk_archive()
    with tempfile.TemporaryDirectory(dir=SDK_PARENT_DIR) as tmp:
        tmp_path = Path(tmp)
        log(f"extracting {archive} into {tmp_path}")
        extract_tar_safely(archive, tmp_path)
        extracted = [path for path in tmp_path.iterdir() if path.is_dir()]
        if len(extracted) != 1:
            fail(f"unexpected Zephyr SDK archive layout in {archive}")
        if SDK_DIR.exists():
            shutil.rmtree(SDK_DIR)
        shutil.move(str(extracted[0]), SDK_DIR)


def ensure_sdk_toolchain() -> None:
    ensure_sdk_extracted()
    gcc = SDK_DIR / "arm-zephyr-eabi" / "bin" / "arm-zephyr-eabi-gcc"
    if gcc.exists():
        log(f"ok: Zephyr SDK arm toolchain already installed: {gcc}")
        return
    setup = SDK_DIR / "setup.sh"
    if not setup.exists():
        fail(f"missing Zephyr SDK setup script: {setup}")
    setup.chmod(setup.stat().st_mode | 0o111)
    run([setup, "-t", *SDK_TOOLCHAINS, "-h"], cwd=SDK_DIR, env=local_env())
    if not gcc.exists():
        fail(f"Zephyr SDK setup completed, but expected compiler was not created: {gcc}")


def verify_local_install() -> None:
    ensure_submodule()
    if not (NCS_DIR / ".west").is_dir():
        fail("missing NCS west workspace; run `just unit::mcu::install`")
    if not ZEPHYR_BASE.is_dir():
        fail("missing NCS Zephyr checkout; run `just unit::mcu::install`")
    if not (SDK_DIR / "arm-zephyr-eabi" / "bin" / "arm-zephyr-eabi-gcc").exists():
        fail("missing local Zephyr SDK arm toolchain; run `just unit::mcu::install`")
    if not VENV_PYTHON.exists():
        fail("missing NCS Python environment; run `just unit::mcu::install`")
    run(west_command() + ["topdir"], cwd=NCS_DIR, env=local_env())


def file_digest(path: Path) -> str:
    if not path.exists():
        fail(f"missing build input: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_recipe_stamp() -> str:
    inputs = {
        "main": MCU_DIR / "src" / "main.c",
        "cmake": APP_DIR / "CMakeLists.txt",
        "kconfig": APP_DIR / "Kconfig",
        "prj": PRJ_CONF,
        "overlay": OVERLAY_FILE,
    }
    lines = [
        f"ncs={NCS_VERSION}",
        f"sdk={SDK_VERSION}",
        f"board={BOARD}",
        f"app={APP_DIR}",
        f"build_version={BUILD_VERSION}",
        "sb_config_partition_manager=n",
    ]
    lines.extend(f"{name}_sha256={file_digest(path)}" for name, path in inputs.items())
    return "\n".join(lines) + "\n"


def build_is_current() -> bool:
    if not (BUILD_DIR / "CMakeCache.txt").exists():
        return False
    if not (BUILD_DIR / "build.ninja").exists():
        return False
    return BUILD_RECIPE_STAMP.exists() and BUILD_RECIPE_STAMP.read_text(
        encoding="utf-8"
    ) == build_recipe_stamp()


def firmware_hex() -> Path:
    candidates = (
        BUILD_DIR / "zephyr" / "zephyr" / "zephyr.hex",
        BUILD_DIR / "zephyr" / "zephyr.hex",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def build_unit(*, pristine: bool) -> None:
    verify_local_install()
    install_python_requirements()
    if pristine or not build_is_current():
        pristine_mode = "always" if BUILD_DIR.exists() or pristine else "auto"
        run(
            west_command()
            + [
                "build",
                "-p",
                pristine_mode,
                "-b",
                BOARD,
                str(APP_DIR),
                "-d",
                str(BUILD_DIR),
                "--",
                f"-DCONF_FILE={PRJ_CONF}",
                "-DSB_CONFIG_PARTITION_MANAGER=n",
                f"-DBUILD_VERSION={BUILD_VERSION}",
            ],
            cwd=NCS_DIR,
            env=local_env(),
        )
    else:
        run(west_command() + ["build", "-d", str(BUILD_DIR)], cwd=NCS_DIR, env=local_env())
    hex_file = firmware_hex()
    if not hex_file.exists():
        fail(f"build completed, but no expected firmware HEX was created: {hex_file}")
    BUILD_RECIPE_STAMP.write_text(build_recipe_stamp(), encoding="utf-8")
    log(f"ok: built {hex_file}")


def install() -> None:
    require_commands("git", "cmake", "ninja", "dtc")
    ensure_submodule()
    ensure_venv()
    ensure_workspace()
    install_python_requirements()
    ensure_sdk_toolchain()


def check() -> None:
    require_commands("git", "cmake", "ninja", "dtc")
    build_unit(pristine=False)


def build() -> None:
    require_commands("git", "cmake", "ninja", "dtc")
    build_unit(pristine=False)


def paths() -> None:
    values = {
        "projectRoot": PROJECT_ROOT,
        "mcuDir": MCU_DIR,
        "ncsDir": NCS_DIR,
        "ncsRepo": NCS_REPO,
        "zephyrBase": ZEPHYR_BASE,
        "sdkDir": SDK_DIR,
        "venv": VENV_DIR,
        "python": VENV_PYTHON,
        "board": BOARD,
        "appDir": APP_DIR,
        "buildDir": BUILD_DIR,
        "firmwareHex": firmware_hex(),
        "openocdCfg": ZEPHYR_BASE / "boards" / "seeed" / "xiao_nrf54l15" / "support" / "openocd.cfg",
        "toolchainVariant": "zephyr",
        "openocdInPath": shutil.which("openocd") or "",
    }
    for label, value in values.items():
        if isinstance(value, Path):
            print(f"{label}: {value} exists={value.exists()}")
        else:
            print(f"{label}: {value}")


def clean() -> None:
    if BUILD_DIR.exists():
        log(f"removing {BUILD_DIR}")
        shutil.rmtree(BUILD_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build txing unit MCU with NCS.")
    parser.add_argument("command", choices=("install", "check", "build", "paths", "clean"))
    args = parser.parse_args()
    if args.command == "install":
        install()
    elif args.command == "check":
        check()
    elif args.command == "build":
        build()
    elif args.command == "paths":
        paths()
    else:
        clean()


if __name__ == "__main__":
    main()
