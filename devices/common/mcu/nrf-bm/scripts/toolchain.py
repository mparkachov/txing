#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import hashlib
import os
import platform
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


BM_REPOSITORY = "https://github.com/nrfconnect/sdk-nrf-bm"
BM_VERSION = "v2.0.0"
SDK_VERSION = "0.17.4"
SDK_RELEASE_BASE = (
    f"https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v{SDK_VERSION}"
)
SDK_TOOLCHAINS = ("arm-zephyr-eabi",)
WEATHER_BOARD = "bm_nrf54l15dk/nrf54l15/cpuapp/s115_softdevice"


NRF_BM_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = NRF_BM_DIR.parents[3]
WORKSPACE_DIR = NRF_BM_DIR / "workspace"
BM_MANIFEST_DIR = WORKSPACE_DIR / "nrf-bm"
ZEPHYR_BASE = WORKSPACE_DIR / "zephyr"
SDK_PARENT_DIR = NRF_BM_DIR / "sdk"
SDK_DIR = SDK_PARENT_DIR / f"zephyr-sdk-{SDK_VERSION}"
DOWNLOADS_DIR = NRF_BM_DIR / "downloads"
VENV_PYTHON = NRF_BM_DIR / ".venv" / "bin" / "python"
LOCAL_HOME = NRF_BM_DIR / ".home"
WEATHER_MCU_DIR = PROJECT_ROOT / "devices" / "weather" / "mcu"
WEATHER_BAREMETAL_DIR = WEATHER_MCU_DIR / "baremetal"
WEATHER_BUILD_DIR = WEATHER_MCU_DIR / "build" / "baremetal-weather"
WEATHER_APP_HEX = WEATHER_BUILD_DIR / "baremetal" / "zephyr" / "zephyr.hex"
WEATHER_APP_ELF = WEATHER_BUILD_DIR / "baremetal" / "zephyr" / "zephyr.elf"
WEATHER_FACTORY_HEX = WEATHER_BUILD_DIR / "txing_weather_factory.hex"
OPENOCD_CFG = WEATHER_MCU_DIR / "support" / "openocd-nrf54l-cmsis-dap.cfg"
BUILD_RECIPE_STAMP = WEATHER_BUILD_DIR / ".txing-nrf-bm-weather-build-recipe"
FACTORY_DATA_ADDRESS = int(os.environ.get("WEATHER_FACTORY_DATA_ADDRESS", "0x000f0000"), 0)
FACTORY_DATA_MAGIC = b"TXW1"
FACTORY_DATA_VERSION = 1
FACTORY_THING_NAME_SIZE = 26
FACTORY_DATA_STRUCT = struct.Struct("<4sBB26sI")
RTT_RAM_START = int(os.environ.get("WEATHER_RTT_RAM_START", "0x20000000"), 0)
RTT_RAM_SIZE = int(os.environ.get("WEATHER_RTT_RAM_SIZE", "0x3b800"), 0)
RTT_PORT = int(os.environ.get("WEATHER_RTT_PORT", "5555"), 0)


REQUIRED_COMMANDS = (
    "uv",
    "just",
    "git",
    "python3",
    "cmake",
    "ninja",
    "gperf",
    "dtc",
    "openocd",
)


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(message)


def validate_thing_name(value: str) -> str:
    thing_name = value.strip()
    if not thing_name:
        fail("AWS thing id must not be empty")
    try:
        encoded = thing_name.encode("ascii")
    except UnicodeEncodeError:
        fail("AWS thing id must be ASCII so it fits in BLE advertising data")
    if len(encoded) > FACTORY_THING_NAME_SIZE:
        fail(
            "AWS thing id is too long for BLE local-name advertising "
            f"({len(encoded)} > {FACTORY_THING_NAME_SIZE} bytes): {thing_name!r}"
        )
    if any(byte < 0x21 or byte > 0x7E for byte in encoded):
        fail("AWS thing id must contain only printable non-space ASCII characters")
    return thing_name


def build_factory_data(thing_name: str) -> bytes:
    normalized = validate_thing_name(thing_name)
    encoded = normalized.encode("ascii")
    name_field = encoded.ljust(FACTORY_THING_NAME_SIZE, b"\0")
    without_crc = FACTORY_DATA_STRUCT.pack(
        FACTORY_DATA_MAGIC,
        FACTORY_DATA_VERSION,
        len(encoded),
        name_field,
        0,
    )[:-4]
    crc = binascii.crc32(without_crc) & 0xFFFFFFFF
    return without_crc + struct.pack("<I", crc)


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    display_cwd = cwd if cwd is not None else NRF_BM_DIR
    log(f"+ ({display_cwd}) {' '.join(args)}")
    return subprocess.run(args, cwd=cwd, env=env, check=check, text=True)


def local_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(LOCAL_HOME)
    env["UV_CACHE_DIR"] = str(NRF_BM_DIR / ".uv-cache")
    env["ZEPHYR_BASE"] = str(ZEPHYR_BASE)
    env["ZEPHYR_SDK_INSTALL_DIR"] = str(SDK_DIR)
    env["ZEPHYR_TOOLCHAIN_VARIANT"] = "zephyr"
    env["Zephyr-sdk_DIR"] = str(SDK_DIR / "cmake")
    env["PATH"] = f"{NRF_BM_DIR / '.venv' / 'bin'}{os.pathsep}{env.get('PATH', '')}"
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
            "Python >=3.12 is required for this BM recipe; "
            f"current interpreter is {version.major}.{version.minor}.{version.micro}"
        )
    log(f"ok: python {version.major}.{version.minor}.{version.micro}")


def which(tool: str) -> str | None:
    return shutil.which(tool, path=local_env().get("PATH"))


def check_host_tools() -> None:
    host_os_arch()
    check_python_version()
    missing: list[str] = []
    for tool in REQUIRED_COMMANDS:
        path = which(tool)
        if path is None:
            missing.append(tool)
        else:
            log(f"ok: {tool} -> {path}")
    if which("curl") is None and which("wget") is None:
        missing.append("curl or wget")
    if missing:
        fail(
            "missing required host tool(s): "
            + ", ".join(missing)
            + "\nInstall host tools manually with Homebrew; see "
            "devices/common/mcu/nrf-bm/README.md."
        )


def ensure_dirs() -> None:
    for path in (DOWNLOADS_DIR, SDK_PARENT_DIR, LOCAL_HOME):
        path.mkdir(parents=True, exist_ok=True)


def west_command() -> list[str]:
    west = NRF_BM_DIR / ".venv" / "bin" / "west"
    if not west.exists():
        fail(
            "west is missing from devices/common/mcu/nrf-bm/.venv; "
            "run `just common::nrf_bm::sync` first"
        )
    return [str(west)]


def ensure_workspace() -> None:
    env = local_env()
    if not (WORKSPACE_DIR / ".west").is_dir():
        WORKSPACE_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(
            west_command()
            + ["init", "-m", BM_REPOSITORY, "--mr", BM_VERSION, str(WORKSPACE_DIR)],
            cwd=NRF_BM_DIR,
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
        if manifest_path != "nrf-bm":
            fail(
                f"unexpected west manifest.path={manifest_path!r}; "
                "expected 'nrf-bm' under devices/common/mcu/nrf-bm/workspace"
            )
        run(
            ["git", "fetch", "--tags", "origin", BM_VERSION],
            cwd=BM_MANIFEST_DIR,
            env=env,
        )
        run(["git", "checkout", "--detach", BM_VERSION], cwd=BM_MANIFEST_DIR, env=env)

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
        fail(
            "devices/common/mcu/nrf-bm/.venv/bin/python is missing; "
            "run `just common::nrf_bm::sync` first"
        )
    requirements = [
        ZEPHYR_BASE / "scripts" / "requirements-base.txt",
        WORKSPACE_DIR / "nrf" / "scripts" / "requirements.txt",
        # The BM runtime requirements include developer-only gitlint, which pins
        # click below the NCS build tooling requirement. Build requirements are
        # enough for this repo-local firmware recipe.
        BM_MANIFEST_DIR / "scripts" / "requirements-build.txt",
    ]
    for path in requirements:
        if not path.exists():
            fail(f"missing requirements file: {path}")
    args = [
        "uv",
        "pip",
        "install",
        "--python",
        str(VENV_PYTHON),
        "--no-managed-python",
        "--no-python-downloads",
        "--strict",
    ]
    for path in requirements:
        args.extend(["--requirements", str(path)])
    run(args, cwd=NRF_BM_DIR, env=local_env())


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
    run([str(setup), "-t", *SDK_TOOLCHAINS, "-h"], cwd=SDK_DIR, env=local_env())
    if not gcc.exists():
        fail(f"SDK setup completed, but expected compiler was not created: {gcc}")


def verify_local_install() -> None:
    if not (WORKSPACE_DIR / ".west").is_dir():
        fail("missing BM workspace; run `just common::nrf_bm::install`")
    if not BM_MANIFEST_DIR.is_dir():
        fail("missing workspace/nrf-bm; run `just common::nrf_bm::install`")
    if not ZEPHYR_BASE.is_dir():
        fail("missing workspace/zephyr; run `just common::nrf_bm::install`")
    if not (SDK_DIR / "arm-zephyr-eabi" / "bin" / "arm-zephyr-eabi-gcc").exists():
        fail("missing local Zephyr SDK arm toolchain; run `just common::nrf_bm::install`")
    if not VENV_PYTHON.exists():
        fail("missing BM Python environment; run `just common::nrf_bm::sync`")
    run(west_command() + ["topdir"], cwd=WORKSPACE_DIR, env=local_env())


def weather_recipe_digest() -> str:
    files = sorted(
        path
        for path in WEATHER_BAREMETAL_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    digest = hashlib.sha256()
    for path in files:
        if not path.exists():
            fail(f"missing weather BM source file: {path}")
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_recipe_stamp() -> str:
    return "\n".join(
        (
            f"nrf_bm={BM_VERSION}",
            f"sdk={SDK_VERSION}",
            f"board={WEATHER_BOARD}",
            f"app={WEATHER_BAREMETAL_DIR.relative_to(PROJECT_ROOT)}",
            f"weather_baremetal_sha256={weather_recipe_digest()}",
            "",
        )
    )


def build_is_current() -> bool:
    if not (WEATHER_BUILD_DIR / "CMakeCache.txt").exists():
        return False
    if not (WEATHER_BUILD_DIR / "build.ninja").exists():
        return False
    return BUILD_RECIPE_STAMP.exists() and BUILD_RECIPE_STAMP.read_text(
        encoding="utf-8"
    ) == build_recipe_stamp()


def softdevice_hex() -> Path:
    path = (
        BM_MANIFEST_DIR
        / "components"
        / "softdevice"
        / "nrf54l"
        / "s115"
        / "s115_nrf54l15_10.0.0_softdevice.hex"
    )
    if not path.exists():
        fail(f"missing S115 SoftDevice HEX: {path}")
    return path


def write_factory_hex(thing_name: str) -> Path:
    from intelhex import IntelHex

    WEATHER_FACTORY_HEX.parent.mkdir(parents=True, exist_ok=True)
    factory = IntelHex()
    factory.puts(FACTORY_DATA_ADDRESS, build_factory_data(thing_name))
    factory.write_hex_file(str(WEATHER_FACTORY_HEX))
    return WEATHER_FACTORY_HEX


def ensure_app_does_not_overlap_factory() -> None:
    from intelhex import IntelHex

    image = IntelHex(str(WEATHER_APP_HEX))
    factory_start = FACTORY_DATA_ADDRESS
    factory_end = FACTORY_DATA_ADDRESS + FACTORY_DATA_STRUCT.size
    for start, end in image.segments():
        if start < factory_end and end > factory_start:
            fail(
                "bare-metal app HEX overlaps weather factory data slot: "
                f"segment 0x{start:08x}-0x{end - 1:08x}, "
                f"factory 0x{factory_start:08x}-0x{factory_end - 1:08x}"
            )


def build_weather_advertising(*, pristine: bool) -> None:
    verify_local_install()
    if pristine or not build_is_current():
        pristine_mode = "always" if pristine or WEATHER_BUILD_DIR.exists() else "never"
        run(
            west_command()
            + [
                "build",
                "-p",
                pristine_mode,
                "-b",
                WEATHER_BOARD,
                str(WEATHER_BAREMETAL_DIR),
                "-d",
                str(WEATHER_BUILD_DIR),
                "--",
                "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE",
            ],
            cwd=WORKSPACE_DIR,
            env=local_env(),
        )
    else:
        run(
            west_command() + ["build", "-d", str(WEATHER_BUILD_DIR)],
            cwd=WORKSPACE_DIR,
            env=local_env(),
        )
    if not WEATHER_APP_HEX.exists():
        fail(
            "build completed, but no expected application HEX was created: "
            f"{WEATHER_APP_HEX}"
        )
    if not WEATHER_APP_ELF.exists():
        fail(
            "build completed, but no expected application ELF was created: "
            f"{WEATHER_APP_ELF}"
        )
    ensure_app_does_not_overlap_factory()
    softdevice_hex()
    BUILD_RECIPE_STAMP.write_text(build_recipe_stamp(), encoding="utf-8")
    log(f"ok: built {WEATHER_APP_HEX}")


def openocd_command() -> str:
    openocd_name = os.environ.get("OPENOCD", "openocd")
    openocd = (
        shutil.which(openocd_name)
        if os.path.sep not in openocd_name
        else openocd_name
    )
    if openocd is None or not Path(openocd).exists():
        fail("openocd is missing; install it manually with Homebrew before flashing")
    return str(openocd)


def openocd_scripts_dir() -> Path:
    configured = os.environ.get("OPENOCD_SCRIPTS")
    candidates = [
        Path(configured) if configured else None,
        Path("/opt/homebrew/share/openocd/scripts"),
        Path("/usr/local/share/openocd/scripts"),
    ]
    for candidate in candidates:
        if (
            candidate is not None
            and (candidate / "interface" / "cmsis-dap.cfg").exists()
        ):
            return candidate
    fail("could not find OpenOCD scripts; set OPENOCD_SCRIPTS")


def tcl_braced_path(path: Path) -> str:
    return "{" + str(path).replace("}", "\\}") + "}"


def flash_hexes(paths: list[Path]) -> None:
    verify_local_install()
    for path in paths:
        if not path.exists():
            fail(f"missing flash image: {path}")
    if not OPENOCD_CFG.exists():
        fail(f"missing OpenOCD config: {OPENOCD_CFG}")

    args = [
        openocd_command(),
        "-s",
        str(openocd_scripts_dir()),
        "-f",
        str(OPENOCD_CFG),
        "-c",
        "init",
        "-c",
        "reset init",
    ]
    for path in paths:
        args.extend(
            [
                "-c",
                f"txing-nrf54l-load {tcl_braced_path(path)}",
                "-c",
                f"verify_image {tcl_braced_path(path)}",
            ]
        )
    args.extend(["-c", "reset run", "-c", "shutdown"])
    run(args, cwd=PROJECT_ROOT, env=local_env())


def flash_hex(path: Path) -> None:
    flash_hexes([path])


def flash_weather(thing_name: str) -> None:
    build_weather_advertising(pristine=False)
    factory_hex = write_factory_hex(thing_name)
    flash_hexes([WEATHER_APP_HEX, factory_hex])


def start_weather_rtt_server() -> None:
    verify_local_install()
    if not OPENOCD_CFG.exists():
        fail(f"missing OpenOCD config: {OPENOCD_CFG}")
    run(
        [
            openocd_command(),
            "-s",
            str(openocd_scripts_dir()),
            "-f",
            str(OPENOCD_CFG),
            "-c",
            "init",
            "-c",
            "reset run",
            "-c",
            "sleep 500",
            "-c",
            "halt",
            "-c",
            f'rtt setup 0x{RTT_RAM_START:08x} 0x{RTT_RAM_SIZE:x} "SEGGER RTT"',
            "-c",
            "rtt start",
            "-c",
            "resume",
            "-c",
            f"rtt server start {RTT_PORT} 0",
        ],
        cwd=PROJECT_ROOT,
        env=local_env(),
    )


def install() -> None:
    check_host_tools()
    ensure_dirs()
    ensure_workspace()
    install_python_requirements()
    ensure_sdk_toolchain()
    build_weather_advertising(pristine=True)


def check() -> None:
    check_host_tools()
    verify_local_install()
    install_python_requirements()
    build_weather_advertising(pristine=False)


def paths() -> None:
    print(f"nrf_bm_root={NRF_BM_DIR}")
    print(f"workspace={WORKSPACE_DIR}")
    print(f"zephyr_base={ZEPHYR_BASE}")
    print(f"zephyr_sdk={SDK_DIR}")
    print(f"weather_build={WEATHER_BUILD_DIR}")
    print(f"weather_app_hex={WEATHER_APP_HEX}")
    print(f"weather_app_elf={WEATHER_APP_ELF}")
    print(f"weather_factory_hex={WEATHER_FACTORY_HEX}")
    print(f"weather_factory_address=0x{FACTORY_DATA_ADDRESS:08x}")
    print(f"weather_rtt_ram=0x{RTT_RAM_START:08x}+0x{RTT_RAM_SIZE:x}")
    print(f"weather_rtt_port={RTT_PORT}")
    print(f"softdevice_hex={softdevice_hex() if BM_MANIFEST_DIR.exists() else ''}")
    print(f"openocd_cfg={OPENOCD_CFG}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install and use the local txing nRF Connect SDK Bare Metal toolchain."
    )
    parser.add_argument(
        "command",
        choices=(
            "install",
            "check",
            "build-weather",
            "build-weather-advertising",
            "flash-weather",
            "flash-weather-advertising",
            "flash-weather-softdevice",
            "rtt-weather",
            "paths",
        ),
    )
    parser.add_argument(
        "thing_name",
        nargs="?",
        help="AWS IoT thing id to store in weather factory data during BM flash",
    )
    args = parser.parse_args()
    if args.command == "install":
        install()
    elif args.command == "check":
        check()
    elif args.command in {"build-weather", "build-weather-advertising"}:
        build_weather_advertising(pristine=False)
    elif args.command == "flash-weather":
        if not args.thing_name:
            fail("flash-weather requires an AWS thing id, e.g. `just weather::mcu::bm-flash weather-q8zbgb`")
        flash_weather(args.thing_name)
    elif args.command == "flash-weather-advertising":
        flash_hex(WEATHER_APP_HEX)
    elif args.command == "flash-weather-softdevice":
        flash_hex(softdevice_hex())
    elif args.command == "rtt-weather":
        start_weather_rtt_server()
    else:
        paths()


if __name__ == "__main__":
    main()
