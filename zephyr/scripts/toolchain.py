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


NCS_REPOSITORY = "https://github.com/nrfconnect/sdk-nrf"
NCS_VERSION = "v3.3.0"
SDK_VERSION = "0.17.4"
SDK_RELEASE_BASE = (
    f"https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v{SDK_VERSION}"
)
BOARD = "xiao_nrf54l15/nrf54l15/cpuapp"
BOARD_BUILD_DIR = "blinky-xiao_nrf54l15_cpuapp"
SDK_TOOLCHAINS = ("arm-zephyr-eabi",)


ZEPHYR_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = ZEPHYR_DIR / "workspace"
NCS_DIR = WORKSPACE_DIR / "nrf"
ZEPHYR_BASE = WORKSPACE_DIR / "zephyr"
SDK_PARENT_DIR = ZEPHYR_DIR / "sdk"
SDK_DIR = SDK_PARENT_DIR / f"zephyr-sdk-{SDK_VERSION}"
DOWNLOADS_DIR = ZEPHYR_DIR / "downloads"
BUILD_DIR = ZEPHYR_DIR / "build" / BOARD_BUILD_DIR
VENV_PYTHON = ZEPHYR_DIR / ".venv" / "bin" / "python"
LOCAL_HOME = ZEPHYR_DIR / ".home"
SYSBUILD_CONF = ZEPHYR_DIR / "config" / "blinky-sysbuild.conf"
BUILD_RECIPE_STAMP = BUILD_DIR / ".txing-zephyr-build-recipe"


REQUIRED_COMMANDS = (
    "uv",
    "just",
    "git",
    "cmake",
    "ninja",
    "gperf",
    "python3",
    "ccache",
    "dtc",
    "openocd",
)

REQUIRED_BREW_FORMULAE = (
    "cmake",
    "ninja",
    "gperf",
    "python",
    "python-tk",
    "ccache",
    "dtc",
    "libmagic",
    "wget",
    "open-ocd",
)


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(message)


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    display_cwd = cwd if cwd is not None else ZEPHYR_DIR
    log(f"+ ({display_cwd}) {' '.join(args)}")
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=check,
        text=True,
    )


def local_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(LOCAL_HOME)
    env["UV_CACHE_DIR"] = str(ZEPHYR_DIR / ".uv-cache")
    env["ZEPHYR_BASE"] = str(ZEPHYR_BASE)
    env["ZEPHYR_SDK_INSTALL_DIR"] = str(SDK_DIR)
    env["ZEPHYR_TOOLCHAIN_VARIANT"] = "zephyr"
    env["PATH"] = f"{ZEPHYR_DIR / '.venv' / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.pop("ZEPHYR_SDK_INSTALL_DIRS", None)
    return env


def host_os_arch() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine()
    if system != "Darwin":
        fail(f"unsupported host OS: {system}; this recipe is for macOS Apple Silicon")
    if machine not in {"arm64", "aarch64"}:
        fail(f"unsupported host architecture: {machine}; expected Apple Silicon arm64")
    return "macos", "aarch64"


def check_python_version() -> None:
    version = sys.version_info
    if version < (3, 12):
        fail(
            "Python >=3.12 is required for this NCS recipe; "
            f"current interpreter is {version.major}.{version.minor}.{version.micro}"
        )
    log(f"ok: python {version.major}.{version.minor}.{version.micro}")


def check_host_tools() -> None:
    host_os_arch()
    check_python_version()
    missing = [tool for tool in REQUIRED_COMMANDS if shutil.which(tool) is None]
    for tool in REQUIRED_COMMANDS:
        path = shutil.which(tool)
        if path is not None:
            log(f"ok: {tool} -> {path}")
    if shutil.which("curl") is None and shutil.which("wget") is None:
        missing.append("curl or wget")
    if missing:
        fail(
            "missing required host tool(s): "
            + ", ".join(missing)
            + "\nInstall host tools manually with Homebrew; see zephyr/README.md."
        )
    check_required_brew_formulae()


def check_required_brew_formulae() -> None:
    brew = shutil.which("brew")
    if brew is None:
        fail("brew was not found; install host tools manually with Homebrew")
    missing: list[str] = []
    for formula in REQUIRED_BREW_FORMULAE:
        result = subprocess.run(
            [brew, "--prefix", formula],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if result.returncode != 0:
            missing.append(formula)
    if missing:
        fail(
            "missing required Homebrew formulae: "
            + ", ".join(missing)
            + "\nInstall host tools manually with Homebrew; see zephyr/README.md."
        )


def ensure_dirs() -> None:
    for path in (DOWNLOADS_DIR, SDK_PARENT_DIR, LOCAL_HOME):
        path.mkdir(parents=True, exist_ok=True)


def west_command() -> list[str]:
    west = ZEPHYR_DIR / ".venv" / "bin" / "west"
    if not west.exists():
        fail("west is missing from zephyr/.venv; run `just zephyr::sync` first")
    return [str(west)]


def ensure_workspace() -> None:
    env = local_env()
    if not (WORKSPACE_DIR / ".west").is_dir():
        WORKSPACE_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(
            west_command()
            + ["init", "-m", NCS_REPOSITORY, "--mr", NCS_VERSION, str(WORKSPACE_DIR)],
            cwd=ZEPHYR_DIR,
            env=env,
        )
    else:
        manifest_path = subprocess.run(
            west_command() + ["config", "manifest.path"],
            cwd=WORKSPACE_DIR,
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        if manifest_path != "nrf":
            fail(
                f"unexpected west manifest.path={manifest_path!r}; "
                "expected 'nrf' under zephyr/workspace"
            )
        run(
            ["git", "fetch", "--tags", "origin", NCS_VERSION],
            cwd=NCS_DIR,
            env=env,
        )
        run(["git", "checkout", "--detach", NCS_VERSION], cwd=NCS_DIR, env=env)

    run(
        west_command() + ["config", "update.narrow", "true"],
        cwd=WORKSPACE_DIR,
        env=env,
    )
    run(
        west_command() + ["update", "--narrow", "--fetch-opt=--filter=blob:none"],
        cwd=WORKSPACE_DIR,
        env=env,
    )


def install_python_requirements() -> None:
    if not VENV_PYTHON.exists():
        fail("zephyr/.venv/bin/python is missing; run `just zephyr::sync` first")
    requirements = [
        ZEPHYR_BASE / "scripts" / "requirements-base.txt",
        NCS_DIR / "scripts" / "requirements.txt",
    ]
    for path in requirements:
        if not path.exists():
            fail(f"missing requirements file: {path}")
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(VENV_PYTHON),
            "--no-managed-python",
            "--no-python-downloads",
            "--strict",
            *sum((["--requirements", str(path)] for path in requirements), []),
        ],
        cwd=ZEPHYR_DIR,
        env=local_env(),
    )


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
    fail(f"could not find {filename} in SDK sha256.sum")


def ensure_downloaded_sdk_archive() -> Path:
    ensure_dirs()
    archive = DOWNLOADS_DIR / sdk_archive_name()
    sha_path = archive.with_suffix(archive.suffix + ".sha256")
    expected = expected_sha256(archive.name)
    if archive.exists():
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest == expected:
            log(f"ok: SDK archive already downloaded: {archive}")
            return archive
        log(f"warn: removing SDK archive with mismatched sha256: {archive}")
        archive.unlink()
    url = sdk_archive_url()
    log(f"downloading {url}")
    data = download_bytes(url)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        fail(f"SDK archive sha256 mismatch: expected {expected}, got {digest}")
    archive.write_bytes(data)
    sha_path.write_text(f"{expected}  {archive.name}\n", encoding="utf-8")
    return archive


def ensure_sdk_extracted() -> None:
    if (SDK_DIR / "setup.sh").exists():
        return
    archive = ensure_downloaded_sdk_archive()
    with tempfile.TemporaryDirectory(dir=SDK_PARENT_DIR) as tmp:
        tmp_path = Path(tmp)
        log(f"extracting {archive} into {tmp_path}")
        with tarfile.open(archive, "r:xz") as tar:
            tar.extractall(tmp_path, filter="data")
        extracted = [path for path in tmp_path.iterdir() if path.is_dir()]
        if len(extracted) != 1:
            fail(f"unexpected SDK archive layout in {archive}")
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
        fail(f"missing SDK setup script: {setup}")
    setup.chmod(setup.stat().st_mode | 0o111)
    run(
        [str(setup), "-t", *SDK_TOOLCHAINS, "-h"],
        cwd=SDK_DIR,
        env=local_env(),
    )
    if not gcc.exists():
        fail(f"SDK setup completed, but expected compiler was not created: {gcc}")


def verify_local_install() -> None:
    if not (WORKSPACE_DIR / ".west").is_dir():
        fail("missing zephyr/workspace/.west; run `just zephyr::install`")
    if not ZEPHYR_BASE.is_dir():
        fail("missing zephyr/workspace/zephyr; run `just zephyr::install`")
    if not (SDK_DIR / "arm-zephyr-eabi" / "bin" / "arm-zephyr-eabi-gcc").exists():
        fail("missing local Zephyr SDK arm toolchain; run `just zephyr::install`")
    if not VENV_PYTHON.exists():
        fail("missing zephyr/.venv; run `just zephyr::sync`")
    run(west_command() + ["topdir"], cwd=WORKSPACE_DIR, env=local_env())


def build_recipe_stamp() -> str:
    if not SYSBUILD_CONF.exists():
        fail(f"missing sysbuild config: {SYSBUILD_CONF}")
    digest = hashlib.sha256(SYSBUILD_CONF.read_bytes()).hexdigest()
    return "\n".join(
        (
            f"ncs={NCS_VERSION}",
            f"sdk={SDK_VERSION}",
            f"board={BOARD}",
            f"sample=samples/basic/blinky",
            f"sysbuild_conf_sha256={digest}",
            "",
        )
    )


def build_is_current() -> bool:
    if not (BUILD_DIR / "CMakeCache.txt").exists():
        return False
    if not (BUILD_DIR / "build.ninja").exists():
        return False
    return BUILD_RECIPE_STAMP.exists() and BUILD_RECIPE_STAMP.read_text(
        encoding="utf-8"
    ) == build_recipe_stamp()


def build_blinky(*, pristine: bool) -> None:
    verify_local_install()
    if pristine or not build_is_current():
        pristine_mode = "always" if pristine or BUILD_DIR.exists() else "never"
        run(
            west_command()
            + [
                "build",
                "-p",
                pristine_mode,
                "-b",
                BOARD,
                "samples/basic/blinky",
                "-d",
                str(BUILD_DIR),
                "--",
                f"-DSB_CONF_FILE={SYSBUILD_CONF}",
            ],
            cwd=ZEPHYR_BASE,
            env=local_env(),
        )
    else:
        run(
            west_command() + ["build", "-d", str(BUILD_DIR)],
            cwd=ZEPHYR_BASE,
            env=local_env(),
        )
    elf_candidates = (
        BUILD_DIR / "blinky" / "zephyr" / "zephyr.elf",
        BUILD_DIR / "zephyr" / "zephyr.elf",
    )
    elf = next((candidate for candidate in elf_candidates if candidate.exists()), None)
    if elf is None:
        expected = ", ".join(str(candidate) for candidate in elf_candidates)
        fail(f"build completed, but no expected ELF was created; checked: {expected}")
    BUILD_RECIPE_STAMP.write_text(build_recipe_stamp(), encoding="utf-8")
    log(f"ok: built {elf}")


def install() -> None:
    check_host_tools()
    ensure_dirs()
    ensure_workspace()
    install_python_requirements()
    ensure_sdk_toolchain()
    build_blinky(pristine=True)


def check() -> None:
    check_host_tools()
    verify_local_install()
    install_python_requirements()
    build_blinky(pristine=False)


def check_flash() -> None:
    check()
    run(
        west_command()
        + [
            "flash",
            "--no-rebuild",
            "-d",
            str(BUILD_DIR),
        ],
        cwd=ZEPHYR_BASE,
        env=local_env(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install and validate the local txing Zephyr/NCS toolchain."
    )
    parser.add_argument("command", choices=("install", "check", "check-flash"))
    args = parser.parse_args()
    if args.command == "install":
        install()
    elif args.command == "check":
        check()
    else:
        check_flash()


if __name__ == "__main__":
    main()
