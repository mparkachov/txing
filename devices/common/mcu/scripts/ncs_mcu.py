#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
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

PROJECT_ROOT = Path(__file__).resolve().parents[4]
MCU_DIR = PROJECT_ROOT / "devices" / "unit" / "mcu"
DEVICE_LABEL = "unit"
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
BUILD_RECIPE_STAMP = BUILD_DIR / f".txing-{DEVICE_LABEL}-ncs-build-recipe"
APP_DIR = MCU_DIR / "zephyr"
PRJ_CONF = APP_DIR / "prj.conf"
OVERLAY_FILE = APP_DIR / "boards" / "xiao_nrf54l15_nrf54l15_cpuapp.overlay"
NCS_MANIFEST_DIR = NCS_DIR / "nrf"
WEST_CONFIG = NCS_DIR / ".west" / "config"

SDK_RELEASE_BASE = (
    f"https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v{SDK_VERSION}"
)


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(message)


def configure(mcu_dir: Path, device_label: str) -> None:
    global MCU_DIR
    global DEVICE_LABEL
    global BUILD_DIR
    global BUILD_RECIPE_STAMP
    global APP_DIR
    global PRJ_CONF
    global OVERLAY_FILE

    if not device_label.replace("-", "").isalnum():
        fail(f"invalid device label: {device_label!r}")

    MCU_DIR = mcu_dir.resolve()
    try:
        MCU_DIR.relative_to(PROJECT_ROOT)
    except ValueError:
        fail(f"MCU directory must be inside the repository: {MCU_DIR}")

    DEVICE_LABEL = device_label
    BUILD_DIR = MCU_DIR / "build" / BUILD_NAME
    BUILD_RECIPE_STAMP = BUILD_DIR / f".txing-{DEVICE_LABEL}-ncs-build-recipe"
    APP_DIR = MCU_DIR / "zephyr"
    PRJ_CONF = APP_DIR / "prj.conf"
    OVERLAY_FILE = APP_DIR / "boards" / "xiao_nrf54l15_nrf54l15_cpuapp.overlay"


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
            f"Run: just {DEVICE_LABEL}::mcu::submodules"
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
            f"Run: just {DEVICE_LABEL}::mcu::submodules"
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
        fail(f"west is missing from {VENV_DIR}; run `just {DEVICE_LABEL}::mcu::install`")
    return [str(west)]


def west_manifest_path() -> str:
    return "nrf"


def ensure_manifest_repo() -> None:
    source_head = run(["git", "rev-parse", "HEAD"], cwd=NCS_REPO, capture=True).stdout.strip()

    if NCS_MANIFEST_DIR.is_symlink():
        log(f"removing stale NCS manifest symlink: {NCS_MANIFEST_DIR}")
        NCS_MANIFEST_DIR.unlink()

    if not NCS_MANIFEST_DIR.exists():
        run(["git", "clone", "--shared", str(NCS_REPO), str(NCS_MANIFEST_DIR)], cwd=NCS_DIR)
    if not (NCS_MANIFEST_DIR / "west.yml").exists():
        fail(f"missing NCS manifest clone at {NCS_MANIFEST_DIR}")

    clone_head = run(
        ["git", "rev-parse", "HEAD"],
        cwd=NCS_MANIFEST_DIR,
        capture=True,
    ).stdout.strip()
    if clone_head != source_head:
        run(["git", "fetch", "origin"], cwd=NCS_MANIFEST_DIR)
        run(["git", "checkout", "--detach", source_head], cwd=NCS_MANIFEST_DIR)


def read_west_manifest_path() -> str | None:
    if not WEST_CONFIG.exists():
        return None
    config = configparser.ConfigParser()
    config.read(WEST_CONFIG, encoding="ascii")
    return config.get("manifest", "path", fallback=None)


def write_west_config() -> None:
    manifest_path = west_manifest_path()
    WEST_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    WEST_CONFIG.write_text(
        "[manifest]\n"
        f"path = {manifest_path}\n"
        "file = west.yml\n",
        encoding="ascii",
    )


def ensure_west_config() -> None:
    ensure_manifest_repo()
    manifest_path = west_manifest_path()
    configured_manifest_path = read_west_manifest_path()
    if configured_manifest_path is None:
        write_west_config()
        log(f"created west workspace config: {WEST_CONFIG}")
        return
    if configured_manifest_path == manifest_path:
        return

    legacy_paths = {
        os.path.relpath(NCS_REPO, NCS_DIR),
        str(NCS_REPO),
    }
    if configured_manifest_path in legacy_paths:
        write_west_config()
        log(
            "updated west manifest.path "
            f"from {configured_manifest_path!r} to {manifest_path!r}"
        )
        return

    fail(
        "unexpected west manifest.path="
        f"{configured_manifest_path!r}; expected {manifest_path!r}"
    )


def ensure_workspace() -> None:
    env = local_env()
    ensure_west_config()
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
    ensure_west_config()
    if not (NCS_DIR / ".west").is_dir():
        fail(f"missing NCS west workspace; run `just {DEVICE_LABEL}::mcu::install`")
    if not ZEPHYR_BASE.is_dir():
        fail(f"missing NCS Zephyr checkout; run `just {DEVICE_LABEL}::mcu::install`")
    if not (SDK_DIR / "arm-zephyr-eabi" / "bin" / "arm-zephyr-eabi-gcc").exists():
        fail(
            "missing local Zephyr SDK arm toolchain; "
            f"run `just {DEVICE_LABEL}::mcu::install`"
        )
    if not VENV_PYTHON.exists():
        fail(f"missing NCS Python environment; run `just {DEVICE_LABEL}::mcu::install`")
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


def build_mcu(*, pristine: bool) -> None:
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
    build_mcu(pristine=False)


def build() -> None:
    require_commands("git", "cmake", "ninja", "dtc")
    build_mcu(pristine=False)


def paths() -> None:
    values = {
        "projectRoot": PROJECT_ROOT,
        "device": DEVICE_LABEL,
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
        "openocdCfg": (
            ZEPHYR_BASE
            / "boards"
            / "seeed"
            / "xiao_nrf54l15"
            / "support"
            / "openocd.cfg"
        ),
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
    parser = argparse.ArgumentParser(
        description="Build a txing XIAO nRF54L15 MCU with NCS."
    )
    parser.add_argument("--mcu-dir", required=True, type=Path)
    parser.add_argument("--device-label", required=True)
    parser.add_argument("command", choices=("install", "check", "build", "paths", "clean"))
    args = parser.parse_args()
    configure(args.mcu_dir, args.device_label)
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
