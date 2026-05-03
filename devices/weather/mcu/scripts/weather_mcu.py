#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


BOARD = "xiao_nrf54l15/nrf54l15/cpuapp"
BUILD_NAME = "weather-xiao_nrf54l15_cpuapp"

MCU_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MCU_DIR.parents[2]
ZEPHYR_DIR = PROJECT_ROOT / "zephyr"
WORKSPACE_DIR = ZEPHYR_DIR / "workspace"
ZEPHYR_BASE = WORKSPACE_DIR / "zephyr"
MATTER_DIR = WORKSPACE_DIR / "modules" / "lib" / "matter"
MATTER_BUILD_REQUIREMENTS = MATTER_DIR / "scripts" / "setup" / "requirements.build.txt"
CLANG_FORMAT_REQUIREMENT = "clang-format==22.1.4"
PYOCD_REQUIREMENT = "pyocd>=0.44,<0.45"
PYOCD_MIN_VERSION = (0, 44, 0)
PYOCD_MAX_VERSION = (0, 45, 0)
OPENOCD_BOARD_SUPPORT_DIR = ZEPHYR_BASE / "boards" / "seeed" / "xiao_nrf54l15" / "support"
OPENOCD_CFG_FILE = OPENOCD_BOARD_SUPPORT_DIR / "openocd.cfg"
PIGWEED_CIPD_CONFIG = (
    MATTER_DIR
    / "third_party"
    / "pigweed"
    / "repo"
    / "pw_env_setup"
    / "py"
    / "pw_env_setup"
    / "cipd_setup"
    / "pigweed.json"
)
SDK_DIR = ZEPHYR_DIR / "sdk" / "zephyr-sdk-0.17.4"
LOCAL_HOME = ZEPHYR_DIR / ".home"
BUILD_ROOT = MCU_DIR / "build"
PIGWEED_ENV_DIR = BUILD_ROOT / "matter-pigweed-env"
PIGWEED_CLANG_FORMAT = PIGWEED_ENV_DIR / "cipd" / "packages" / "pigweed" / "bin" / "clang-format"
APP_DIR = MCU_DIR / "app"
COMMON_MATTER_DIR = PROJECT_ROOT / "devices" / "common" / "mcu" / "matter"
GENERATED_DIR = BUILD_ROOT / "generated"
GENERATED_KEY_DIR = GENERATED_DIR / "keys"
BUILD_DIR = BUILD_ROOT / BUILD_NAME
BUILD_RECIPE_STAMP = BUILD_DIR / ".txing-weather-build-recipe"
MERGED_HEX_FILE = BUILD_DIR / "txing_weather_merged.hex"
FLASH_CHUNK_DIR = BUILD_DIR / "flash-chunks"
FLASH_VERIFY_DIR = BUILD_DIR / "flash-verify"
DEV_SIGNING_KEY_FILE = GENERATED_KEY_DIR / "txing_weather_dev_ed25519.pem"
SYSBUILD_EXTRA_CONF_FILE = GENERATED_DIR / "sysbuild-extra.conf"
COMMON_CONF_FILE = COMMON_MATTER_DIR / "config" / "thread_sed.conf"
OVERLAY_FILE = MCU_DIR / "config" / "xiao_nrf54l15_bme280.overlay"
CONF_FILE = MCU_DIR / "config" / "xiao_nrf54l15_cpuapp.conf"


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(message)


def west_command() -> list[str]:
    west = ZEPHYR_DIR / ".venv" / "bin" / "west"
    if not west.exists():
        fail("west is missing from zephyr/.venv; run `just zephyr::install` first")
    return [str(west)]


def local_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(LOCAL_HOME)
    env["UV_CACHE_DIR"] = str(ZEPHYR_DIR / ".uv-cache")
    env["ZEPHYR_BASE"] = str(ZEPHYR_BASE)
    env["ZEPHYR_SDK_INSTALL_DIR"] = str(SDK_DIR)
    env["ZEPHYR_TOOLCHAIN_VARIANT"] = "zephyr"
    env["PATH"] = f"{ZEPHYR_DIR / '.venv' / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    if PIGWEED_CLANG_FORMAT.exists():
        env["PW_ENVIRONMENT_ROOT"] = str(PIGWEED_ENV_DIR)
    env.pop("ZEPHYR_SDK_INSTALL_DIRS", None)
    return env


def run(args: list[str], *, cwd: Path) -> None:
    log(f"+ ({cwd}) {' '.join(args)}")
    subprocess.run(args, cwd=cwd, env=local_env(), check=True, text=True)


def run_with_retries(args: list[str], *, cwd: Path, attempts: int, retry_delay_seconds: int) -> None:
    for attempt in range(1, attempts + 1):
        log(f"+ ({cwd}) {' '.join(args)}")
        result = subprocess.run(args, cwd=cwd, env=local_env(), check=False, text=True)
        if result.returncode == 0:
            return
        if attempt == attempts:
            result.check_returncode()
        log(f"pyOCD command failed on attempt {attempt}/{attempts}; retrying in {retry_delay_seconds}s")
        time.sleep(retry_delay_seconds)


def run_capture(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=local_env(),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def env_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def env_int(name: str, *, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value, 0)
    except ValueError:
        fail(f"{name} must be an integer, got {value!r}")
    if parsed < 0:
        fail(f"{name} must be >= 0, got {value!r}")
    return parsed


def verify_toolchain() -> None:
    missing_tools = [tool for tool in ("cmake", "ninja", "gn") if shutil.which(tool) is None]
    if missing_tools:
        fail(
            "missing required host tool(s) for the Matter weather firmware build: "
            + ", ".join(missing_tools)
            + "\nInstall them manually with Homebrew; see devices/weather/mcu/README.md."
        )
    required_paths = (
        WORKSPACE_DIR / ".west",
        ZEPHYR_BASE,
        APP_DIR / "CMakeLists.txt",
        COMMON_MATTER_DIR / "cmake" / "txing_matter.cmake",
        MATTER_BUILD_REQUIREMENTS,
        SDK_DIR / "arm-zephyr-eabi" / "bin" / "arm-zephyr-eabi-gcc",
        ZEPHYR_DIR / ".venv" / "bin" / "python",
    )
    for path in required_paths:
        if not path.exists():
            fail(f"missing required Zephyr/NCS toolchain path: {path}\nRun `just zephyr::install` first.")


def ensure_matter_python_requirements() -> None:
    python = ZEPHYR_DIR / ".venv" / "bin" / "python"
    result = run_capture(
        [
            str(python),
            "-c",
            "import clang_format, click, coloredlogs, jinja2, lark, python_path",
        ],
        cwd=MCU_DIR,
        check=False,
    )
    if result.returncode == 0:
        return
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-managed-python",
            "--no-python-downloads",
            "--strict",
            "--requirements",
            str(MATTER_BUILD_REQUIREMENTS),
            CLANG_FORMAT_REQUIREMENT,
        ],
        cwd=ZEPHYR_DIR,
    )


def pigweed_clang_revision() -> str | None:
    if not PIGWEED_CIPD_CONFIG.exists():
        return None
    config = json.loads(PIGWEED_CIPD_CONFIG.read_text(encoding="utf-8"))
    clang_package = next(
        (
            package
            for package in config.get("packages", [])
            if package.get("path", "").startswith("fuchsia/third_party/clang/")
        ),
        None,
    )
    if clang_package is None:
        return None
    tag = clang_package.get("tags", [""])[0]
    prefix, _, revision = tag.partition(":")
    if prefix != "git_revision" or not revision:
        return None
    return revision


def ensure_clang_format_wrapper() -> None:
    revision = pigweed_clang_revision()
    real_clang_format = ZEPHYR_DIR / ".venv" / "bin" / "clang-format"
    if revision is None or not real_clang_format.exists():
        return

    PIGWEED_CLANG_FORMAT.parent.mkdir(parents=True, exist_ok=True)
    wrapper = f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "--version" ]; then
  echo "Fuchsia clang-format version txing-local ({revision})"
  exit 0
fi
exec "{real_clang_format}" "$@"
"""
    if PIGWEED_CLANG_FORMAT.exists() and PIGWEED_CLANG_FORMAT.read_text(encoding="utf-8") == wrapper:
        return
    PIGWEED_CLANG_FORMAT.write_text(wrapper, encoding="utf-8")
    PIGWEED_CLANG_FORMAT.chmod(0o755)


def parse_version(value: str) -> tuple[int, ...]:
    match = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value.strip())
    if match is None:
        return ()
    return tuple(int(part) for part in match.groups(default="0"))


def ensure_flash_python_requirements() -> None:
    python = ZEPHYR_DIR / ".venv" / "bin" / "python"
    result = run_capture(
        [
            str(python),
            "-c",
            "from importlib.metadata import version; print(version('pyocd'))",
        ],
        cwd=MCU_DIR,
        check=False,
    )
    if result.returncode == 0:
        installed_version = parse_version(result.stdout)
        if PYOCD_MIN_VERSION <= installed_version < PYOCD_MAX_VERSION:
            return
        log(
            "updating pyOCD from "
            f"{result.stdout.strip()} to {PYOCD_REQUIREMENT}; "
            "older pyOCD releases are unreliable on XIAO nRF54L15 Matter images"
        )
    else:
        log(f"installing {PYOCD_REQUIREMENT} into zephyr/.venv")

    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-managed-python",
            "--no-python-downloads",
            "--strict",
            "--upgrade",
            PYOCD_REQUIREMENT,
        ],
        cwd=ZEPHYR_DIR,
    )
    result = run_capture(
        [
            str(python),
            "-c",
            "from importlib.metadata import version; print(version('pyocd'))",
        ],
        cwd=MCU_DIR,
        check=False,
    )
    if result.returncode != 0:
        fail(f"failed to install {PYOCD_REQUIREMENT}")
    installed_version = parse_version(result.stdout)
    if not (PYOCD_MIN_VERSION <= installed_version < PYOCD_MAX_VERSION):
        fail(
            f"installed unsupported pyOCD {result.stdout.strip()}; "
            f"expected {PYOCD_REQUIREMENT}"
        )


def ensure_dev_signing_key() -> None:
    if DEV_SIGNING_KEY_FILE.exists():
        return
    imgtool = WORKSPACE_DIR / "bootloader" / "mcuboot" / "scripts" / "imgtool.py"
    if not imgtool.exists():
        fail(f"missing MCUboot imgtool: {imgtool}\nRun `just zephyr::install` first.")
    DEV_SIGNING_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            sys.executable,
            str(imgtool),
            "keygen",
            "-k",
            str(DEV_SIGNING_KEY_FILE),
            "-t",
            "ed25519",
        ],
        cwd=MCU_DIR,
    )


def ensure_generated_sysbuild_extra_conf() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    content = f"""# Generated by devices/weather/mcu/scripts/weather_mcu.py.
# Keep generated build-time paths out of tracked sysbuild.conf.
SB_CONFIG_PARTITION_MANAGER=n
SB_CONFIG_BOOT_SIGNATURE_TYPE_ED25519=y
SB_CONFIG_BOOT_SIGNATURE_TYPE_PURE=y
SB_CONFIG_BOOT_SIGNATURE_KEY_FILE="{DEV_SIGNING_KEY_FILE}"
"""
    if SYSBUILD_EXTRA_CONF_FILE.exists() and SYSBUILD_EXTRA_CONF_FILE.read_text(encoding="utf-8") == content:
        return
    SYSBUILD_EXTRA_CONF_FILE.write_text(content, encoding="utf-8")


def recipe_input_paths() -> list[Path]:
    roots = (APP_DIR, COMMON_MATTER_DIR, MCU_DIR / "config")
    paths: list[Path] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                paths.append(path)
    return sorted(paths)


def recipe_stamp() -> str:
    digest = hashlib.sha256()
    for path in recipe_input_paths():
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "\n".join(
        (
            "source=devices/weather/mcu/app",
            "common=devices/common/mcu/matter",
            "recipe=txing-weather-direct-matter-bme280-v1",
            f"board={BOARD}",
            f"source_sha256={digest.hexdigest()}",
            "",
        )
    )


def build_is_current() -> bool:
    if not (BUILD_DIR / "CMakeCache.txt").exists():
        return False
    return BUILD_RECIPE_STAMP.exists() and BUILD_RECIPE_STAMP.read_text(encoding="utf-8") == recipe_stamp()


def app_image_dirs() -> tuple[Path, ...]:
    return (
        BUILD_DIR / "app",
        BUILD_DIR / "txing_weather",
        BUILD_DIR / "txing-weather-matter",
        BUILD_DIR / "source",
        BUILD_DIR,
    )


def app_image_file(name: str) -> Path:
    candidates = [image_dir / "zephyr" / name for image_dir in app_image_dirs()]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    fail(
        "weather build completed, but expected app image file was not created: "
        + name
        + "\nChecked:\n"
        + "\n".join(f"- {candidate}" for candidate in candidates)
    )


def build(*, pristine: bool) -> None:
    verify_toolchain()
    ensure_matter_python_requirements()
    ensure_clang_format_wrapper()
    ensure_dev_signing_key()
    ensure_generated_sysbuild_extra_conf()
    if pristine or not build_is_current():
        pristine_mode = "always" if BUILD_DIR.exists() else "never"
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
                f"-DEXTRA_CONF_FILE={COMMON_CONF_FILE};{CONF_FILE}",
                f"-DEXTRA_DTC_OVERLAY_FILE={OVERLAY_FILE}",
                f"-DSB_EXTRA_CONF_FILE={SYSBUILD_EXTRA_CONF_FILE}",
            ],
            cwd=ZEPHYR_BASE,
        )
    else:
        run(west_command() + ["build", "-d", str(BUILD_DIR)], cwd=ZEPHYR_BASE)

    elf = app_image_file("zephyr.elf")
    BUILD_RECIPE_STAMP.write_text(recipe_stamp(), encoding="utf-8")
    log(f"ok: built {elf}")


def merge_flash_hex() -> Path:
    from intelhex import IntelHex

    bootloader_hex = BUILD_DIR / "mcuboot" / "zephyr" / "zephyr.hex"
    app_hex = app_image_file("zephyr.signed.hex")
    for path in (bootloader_hex, app_hex):
        if not path.exists():
            fail(f"missing flash image: {path}\nRun `just weather::mcu::check` first.")

    merged = IntelHex()
    merged.merge(IntelHex(str(bootloader_hex)), overlap="error")
    merged.merge(IntelHex(str(app_hex)), overlap="error")
    merged.write_hex_file(str(MERGED_HEX_FILE))
    return MERGED_HEX_FILE


def split_flash_hex(hex_file: Path, *, chunk_size: int) -> list[Path]:
    if chunk_size == 0:
        return [hex_file]
    if chunk_size % 0x1000 != 0:
        fail("PYOCD_CHUNK_SIZE must be a multiple of 0x1000 so sector erase does not overlap chunks")

    from intelhex import IntelHex

    source = IntelHex(str(hex_file))
    segments = source.segments()
    if not segments:
        fail(f"no flashable data found in {hex_file}")

    if FLASH_CHUNK_DIR.exists():
        shutil.rmtree(FLASH_CHUNK_DIR)
    FLASH_CHUNK_DIR.mkdir(parents=True)

    chunks: list[Path] = []
    min_address = min(start for start, _ in segments)
    max_address = max(end for _, end in segments)
    window_start = min_address - (min_address % chunk_size)

    while window_start < max_address:
        window_end = window_start + chunk_size
        chunk = IntelHex()
        for segment_start, segment_end in segments:
            copy_start = max(segment_start, window_start)
            copy_end = min(segment_end, window_end)
            if copy_start < copy_end:
                chunk.puts(copy_start, bytes(source.tobinarray(start=copy_start, end=copy_end - 1)))

        if chunk.addresses():
            path = FLASH_CHUNK_DIR / (
                f"chunk-{len(chunks) + 1:03d}-{window_start:08x}-{window_end - 1:08x}.hex"
            )
            chunk.write_hex_file(str(path))
            chunks.append(path)
        window_start = window_end

    if not chunks:
        fail(f"no flashable data found in {hex_file}")
    return chunks


def chunk_window(chunk: Path) -> tuple[int, int]:
    match = re.match(r"chunk-\d+-([0-9a-f]{8})-([0-9a-f]{8})\.hex$", chunk.name)
    if match is None:
        fail(f"unexpected flash chunk filename: {chunk.name}")
    start = int(match.group(1), 16)
    end = int(match.group(2), 16) + 1
    return start, end


def flash_compare_bins(chunks: list[Path]) -> list[tuple[int, int, Path]]:
    from intelhex import IntelHex

    if FLASH_VERIFY_DIR.exists():
        shutil.rmtree(FLASH_VERIFY_DIR)
    FLASH_VERIFY_DIR.mkdir(parents=True)

    compare_bins: list[tuple[int, int, Path]] = []
    for chunk in chunks:
        start, end = chunk_window(chunk)
        image = IntelHex(str(chunk))
        image.padding = 0xFF
        data = bytes(image.tobinarray(start=start, end=end - 1))
        path = FLASH_VERIFY_DIR / f"{chunk.stem}.bin"
        path.write_bytes(data)
        compare_bins.append((start, end - start, path))
    return compare_bins


def tcl_braced_path(path: Path) -> str:
    text = str(path)
    if "}" in text:
        fail(f"cannot pass path containing '}}' to OpenOCD Tcl command: {path}")
    return "{" + text + "}"


def openocd_load_command(path: Path) -> str:
    return (
        f"if {{[catch {{txing-nrf54l-load {tcl_braced_path(path)}}} result]}} {{ "
        'echo "RRAMC ACCESSERRORADDR:"; '
        "mdw 0x5004b408 1; "
        'echo "RRAMC CONFIG:"; '
        "mdw 0x5004b500 1; "
        'echo "RRAMC BUFSTATUS:"; '
        "mdw 0x5004b410 1; "
        "error $result "
        "}"
    )


def openocd_script_args() -> list[str]:
    args = ["-s", str(OPENOCD_BOARD_SUPPORT_DIR)]
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


def flash_openocd(merged_hex: Path) -> None:
    openocd_name = os.environ.get("OPENOCD", "openocd")
    openocd = shutil.which(openocd_name) if os.path.sep not in openocd_name else openocd_name
    if openocd is None or not Path(openocd).exists():
        fail("openocd is missing; install it manually with Homebrew before flashing")
    if not OPENOCD_CFG_FILE.exists():
        fail(f"missing XIAO nRF54L15 OpenOCD config: {OPENOCD_CFG_FILE}")

    frequency = os.environ.get("OPENOCD_FREQUENCY", "100")
    # Zephyr's board helper uses 0x101: write-enable plus one 128-bit write
    # buffer. The larger Matter image has been observed to fail mid-image with
    # that buffered path, so default to unbuffered RRAM writes.
    rramc_config = os.environ.get("OPENOCD_RRAMC_CONFIG", "0x1")
    run(
        [
            str(openocd),
            *openocd_script_args(),
            "-f",
            str(OPENOCD_CFG_FILE),
            "-c",
            (
                "proc txing-nrf54l-load {file} { "
                f"mww 0x5004b500 {rramc_config}; "
                "load_image $file; "
                "mww 0x5004b500 0x0 "
                "}"
            ),
            "-c",
            f"adapter speed {frequency}",
            "-c",
            "init",
            "-c",
            "targets",
            "-c",
            "reset init",
            "-c",
            openocd_load_command(merged_hex),
            "-c",
            "reset run",
            "-c",
            "shutdown",
        ],
        cwd=MCU_DIR,
    )


def flash_pyocd(merged_hex: Path) -> None:
    ensure_flash_python_requirements()
    pyocd = ZEPHYR_DIR / ".venv" / "bin" / "pyocd"
    probe_uid = os.environ.get("PYOCD_PROBE_UID") or os.environ.get("PYOCD_PROBE")
    probe_args = ["--uid", probe_uid] if probe_uid else []
    frequency = os.environ.get("PYOCD_FREQUENCY", "50000")
    connect_mode = os.environ.get("PYOCD_CONNECT", "halt")
    chunk_size = env_int("PYOCD_CHUNK_SIZE", default=0x4000)
    chunk_attempts = max(env_int("PYOCD_CHUNK_RETRIES", default=3), 1)
    retry_delay_seconds = env_int("PYOCD_RETRY_DELAY_SECONDS", default=2)
    extra_args = shlex.split(os.environ.get("PYOCD_EXTRA_ARGS", ""))
    common_args = [
        "--no-config",
        "-O",
        "dap_protocol=swd",
        "-O",
        "smart_flash=false",
        "-O",
        "keep_unwritten=false",
        "-O",
        "cmsis_dap.deferred_transfers=false",
        "-O",
        "cmsis_dap.limit_packets=true",
        "--target",
        "nrf54l",
        "--frequency",
        frequency,
        "--connect",
        connect_mode,
        *probe_args,
        *extra_args,
    ]
    if env_flag("PYOCD_MASS_ERASE", default=True):
        run([str(pyocd), "erase", *common_args, "--mass"], cwd=MCU_DIR)
    chunks = split_flash_hex(merged_hex, chunk_size=chunk_size)
    if len(chunks) > 1:
        log(f"programming {len(chunks)} pyOCD chunks of at most {chunk_size} bytes")
    no_reset_args = ["--no-reset"] if env_flag("PYOCD_NO_RESET", default=True) else []
    for index, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            log(f"programming pyOCD chunk {index}/{len(chunks)}: {chunk.name}")
        run_with_retries(
            [
                str(pyocd),
                "load",
                *common_args,
                "--erase",
                "sector",
                "--format",
                "hex",
                *no_reset_args,
                str(chunk),
            ],
            cwd=MCU_DIR,
            attempts=chunk_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
    if env_flag("PYOCD_RESET_AFTER_LOAD", default=False):
        run([str(pyocd), "reset", *common_args], cwd=MCU_DIR)
    log(f"ok: programmed {len(chunks)} pyOCD chunks from {merged_hex}")
    if env_flag("PYOCD_NO_RESET", default=True) and not env_flag("PYOCD_RESET_AFTER_LOAD", default=False):
        log("target was left halted by --no-reset; press reset or power-cycle the board before using it")


def verify_flash() -> None:
    build(pristine=False)
    merged_hex = merge_flash_hex()
    ensure_flash_python_requirements()

    pyocd = ZEPHYR_DIR / ".venv" / "bin" / "pyocd"
    probe_uid = os.environ.get("PYOCD_PROBE_UID") or os.environ.get("PYOCD_PROBE")
    probe_args = ["--uid", probe_uid] if probe_uid else []
    frequency = os.environ.get("PYOCD_FREQUENCY", "50000")
    connect_mode = os.environ.get("PYOCD_CONNECT", "halt")
    chunk_size = env_int("PYOCD_CHUNK_SIZE", default=0x4000)
    attempts = max(env_int("PYOCD_VERIFY_RETRIES", default=3), 1)
    retry_delay_seconds = env_int("PYOCD_RETRY_DELAY_SECONDS", default=2)
    extra_args = shlex.split(os.environ.get("PYOCD_EXTRA_ARGS", ""))
    common_args = [
        "--no-config",
        "-O",
        "dap_protocol=swd",
        "-O",
        "cmsis_dap.deferred_transfers=false",
        "-O",
        "cmsis_dap.limit_packets=true",
        "--target",
        "nrf54l",
        "--frequency",
        frequency,
        "--connect",
        connect_mode,
        *probe_args,
        *extra_args,
    ]

    chunks = split_flash_hex(merged_hex, chunk_size=chunk_size)
    compare_bins = flash_compare_bins(chunks)
    log(f"verifying {len(compare_bins)} flash chunks")
    for index, (start, length, compare_bin) in enumerate(compare_bins, start=1):
        log(f"verifying pyOCD chunk {index}/{len(compare_bins)}: {compare_bin.name}")
        run_with_retries(
            [
                str(pyocd),
                "commander",
                *common_args,
                "-c",
                f"compare 0x{start:x} 0x{length:x} {compare_bin}",
            ],
            cwd=MCU_DIR,
            attempts=attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
    log(f"ok: verified {len(compare_bins)} pyOCD chunks against {merged_hex}")


def flash() -> None:
    build(pristine=False)
    merged_hex = merge_flash_hex()
    runner = os.environ.get("WEATHER_MCU_FLASH_RUNNER", "pyocd").lower()
    if runner == "openocd":
        flash_openocd(merged_hex)
    elif runner == "pyocd":
        flash_pyocd(merged_hex)
    else:
        fail("unsupported WEATHER_MCU_FLASH_RUNNER; expected `openocd` or `pyocd`")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build txing weather firmware with the local Zephyr/NCS recipe.")
    parser.add_argument("command", choices=("check", "build", "flash", "verify"))
    args = parser.parse_args()
    if args.command == "flash":
        flash()
    elif args.command == "verify":
        verify_flash()
    else:
        build(pristine=False)


if __name__ == "__main__":
    main()
