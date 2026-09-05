#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import os
import shutil
import shlex
import subprocess
import sys
from pathlib import Path


ZEPHYR_VERSION = os.environ.get("TXING_ZEPHYR_VERSION", "main")
ZEPHYR_REPO = "https://github.com/zephyrproject-rtos/zephyr"
BUILD_VERSION = os.environ.get("TXING_BUILD_VERSION", f"zephyr-{ZEPHYR_VERSION}")
NVE_ADDRESS = "0x000f0000"
VENV_PYTHON_VERSION = "3.12"

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
UV_CACHE_DIR = COMMON_MCU_DIR / ".uv-cache"
ZEPHYR_CACHE_DIR = COMMON_MCU_DIR / ".zephyr-cache"
CCACHE_DIR = COMMON_MCU_DIR / ".ccache"
NVE_SCRIPT = COMMON_MCU_DIR / "xiao_nrf54l15" / "scripts" / "redcon_nve.py"
BOARD_CONF = COMMON_MCU_DIR / "xiao_nrf54l15" / "board.conf"
THREAD_FACTORY_SCRIPT = COMMON_MCU_DIR / "xiao_mg24" / "scripts" / "thread_factory.py"
POWER_NRF_FACTORY_SCRIPT = (
    COMMON_MCU_DIR / "xiao_nrf54lm20a" / "scripts" / "thread_factory.py"
)
COMMON_BUILD_DIR = COMMON_MCU_DIR / "build"
NVE_HEX = COMMON_BUILD_DIR / "redcon-factory-nve.hex"
POWER_SI_FACTORY_HEX = COMMON_BUILD_DIR / "power-si-thread-factory.hex"
POWER_NRF_FACTORY_HEX = COMMON_BUILD_DIR / "power-nrf-thread-factory.hex"
TBOT_FACTORY_HEX = COMMON_BUILD_DIR / "tbot-thread-factory.hex"
NRF_OPENOCD_SUPPORT_DIR = ZEPHYR_BASE / "boards" / "seeed" / "xiao_nrf54l15" / "support"
NRF_OPENOCD_CFG = NRF_OPENOCD_SUPPORT_DIR / "openocd.cfg"
POWER_NRF_OPENOCD_SUPPORT_DIR = (
    ZEPHYR_BASE / "boards" / "seeed" / "xiao_nrf54lm20a" / "support"
)
POWER_NRF_OPENOCD_CFG = POWER_NRF_OPENOCD_SUPPORT_DIR / "openocd.cfg"
PYOCD_REQUIRED_TARGETS = ("EFR32MG24B220F1536IM48",)
PYOCD_PACK_TARGETS = PYOCD_REQUIRED_TARGETS
HAL_SILABS_DIR = WORKSPACE_DIR / "modules" / "hal" / "silabs"
HAL_SILABS_BLOBS_DIR = HAL_SILABS_DIR / "zephyr" / "blobs"
POWER_SI_BLOB_REGEX = (
    r"simplicity_sdk/("
    r"protocol/openthread/.*/libsl_openthread\.a|"
    r"platform/radio/rail_lib/autogen/librail_release/"
    r"librail_(multiprotocol_)?efr32xg24_gcc_release\.a"
    r")"
)
POWER_SI_REQUIRED_BLOBS = (
    HAL_SILABS_BLOBS_DIR
    / "simplicity_sdk"
    / "protocol"
    / "openthread"
    / "build"
    / "gcc"
    / "cortex-m33"
    / "cmake"
    / "sl-openthread-library"
    / "Release"
    / "libsl_openthread.a",
    HAL_SILABS_BLOBS_DIR
    / "simplicity_sdk"
    / "platform"
    / "radio"
    / "rail_lib"
    / "autogen"
    / "librail_release"
    / "librail_efr32xg24_gcc_release.a",
)
@dataclass(frozen=True)
class IsolatedPatch:
    checkout: Path
    patch: Path


@dataclass(frozen=True)
class BuildProfile:
    name: str
    build_suffix: str = ""
    debug_conf: bool = False
    sed_debug_conf: bool = False
    release_conf: bool = False
    use_silabs_ccm_candidate: bool = False
    force_pristine: bool = False


POWER_SI_SILABS_CCM_PATCH_ENV = "TXING_POWER_SI_SILABS_CCM_PATCH"
POWER_SI_SILABS_CCM_PATCHES = (
    IsolatedPatch(
        HAL_SILABS_DIR,
        COMMON_MCU_DIR / "patches" / "silabs-radioaes-zero-length-ccm.patch",
    ),
)
BUILD_PROFILES = {
    profile.name: profile
    for profile in (
        BuildProfile("release"),
        BuildProfile("debug", build_suffix="-debug", debug_conf=True, force_pristine=True),
        BuildProfile(
            "sed-debug",
            build_suffix="-sed-debug",
            debug_conf=True,
            sed_debug_conf=True,
            use_silabs_ccm_candidate=True,
            force_pristine=True,
        ),
    )
}
ACTIVE_BUILD_PROFILES = tuple(BUILD_PROFILES)

POWER_SI_RELEASE_PROFILE = BuildProfile(
    "release",
    sed_debug_conf=True,
    release_conf=True,
    use_silabs_ccm_candidate=True,
    force_pristine=True,
)

POWER_NRF_RELEASE_PROFILE = BuildProfile(
    "release",
    release_conf=True,
    force_pristine=True,
)

POWER_NRF_SED_DEBUG_PROFILE = BuildProfile(
    "sed-debug",
    build_suffix="-sed-debug",
    debug_conf=True,
    sed_debug_conf=True,
    force_pristine=True,
)


@dataclass(frozen=True)
class DeviceConfig:
    board: str
    build_name: str
    overlay_name: str
    extra_conf: Path | None = None
    debug_conf: Path | None = None
    sed_debug_conf: Path | None = None
    release_conf: Path | None = None
    flash_runner: str | None = None


NRF_CONFIG = DeviceConfig(
    board="xiao_nrf54l15/nrf54l15/cpuapp",
    build_name="zephyr-xiao_nrf54l15_cpuapp",
    overlay_name="xiao_nrf54l15_nrf54l15_cpuapp.overlay",
    extra_conf=BOARD_CONF,
    flash_runner="openocd-nrf54l15",
)

DEVICE_CONFIGS = {
    "power": NRF_CONFIG,
    "weather": NRF_CONFIG,
    "unit": NRF_CONFIG,
    "power-si": DeviceConfig(
        board="xiao_mg24",
        build_name="zephyr-xiao_mg24",
        overlay_name="xiao_mg24.overlay",
        debug_conf=PROJECT_ROOT
        / "devices"
        / "power-si"
        / "mcu"
        / "zephyr"
        / "debug.conf",
        sed_debug_conf=PROJECT_ROOT
        / "devices"
        / "power-si"
        / "mcu"
        / "zephyr"
        / "sed-debug.conf",
        release_conf=PROJECT_ROOT
        / "devices"
        / "power-si"
        / "mcu"
        / "zephyr"
        / "release.conf",
        flash_runner="west-pyocd",
    ),
    "power-nrf": DeviceConfig(
        board="xiao_nrf54lm20a/nrf54lm20a/cpuapp",
        build_name="zephyr-xiao_nrf54lm20a_nrf54lm20a_cpuapp",
        overlay_name="xiao_nrf54lm20a_nrf54lm20a_cpuapp.overlay",
        debug_conf=PROJECT_ROOT
        / "devices"
        / "power-nrf"
        / "mcu"
        / "zephyr"
        / "debug.conf",
        sed_debug_conf=PROJECT_ROOT
        / "devices"
        / "power-nrf"
        / "mcu"
        / "zephyr"
        / "sed-debug.conf",
        release_conf=PROJECT_ROOT
        / "devices"
        / "power-nrf"
        / "mcu"
        / "zephyr"
        / "release.conf",
        flash_runner="openocd-nrf54lm20a",
    ),
    "tbot": DeviceConfig(
        board="xiao_nrf54lm20a/nrf54lm20a/cpuapp",
        build_name="zephyr-xiao_nrf54lm20a_nrf54lm20a_cpuapp",
        overlay_name="xiao_nrf54lm20a_nrf54lm20a_cpuapp.overlay",
        debug_conf=PROJECT_ROOT
        / "devices"
        / "tbot"
        / "mcu"
        / "zephyr"
        / "debug.conf",
        sed_debug_conf=PROJECT_ROOT
        / "devices"
        / "tbot"
        / "mcu"
        / "zephyr"
        / "sed-debug.conf",
        release_conf=PROJECT_ROOT
        / "devices"
        / "tbot"
        / "mcu"
        / "zephyr"
        / "release.conf",
        flash_runner="openocd-nrf54lm20a",
    ),
}
ACTIVE_DEVICES = tuple(DEVICE_CONFIGS)


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
    env["UV_CACHE_DIR"] = str(UV_CACHE_DIR)
    env["ZEPHYR_CACHE_DIR"] = str(ZEPHYR_CACHE_DIR)
    env["CCACHE_DIR"] = str(CCACHE_DIR)
    env["PATH"] = f"{VENV_DIR / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.pop("BOARD_ROOT", None)
    env.pop("POWER_BOARD_ROOT", None)
    env.pop("ZEPHYR_MODULES", None)
    env.pop("ZEPHYR_SDK_INSTALL_DIRS", None)
    env.pop("ZEPHYR_SDK_INSTALL_DIR", None)
    env.pop("CROSS_COMPILE", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env.pop("PIP_PREFIX", None)
    env.pop("PIP_TARGET", None)
    env.pop("PIP_USER", None)
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
        UV_CACHE_DIR,
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
    if VENV_DIR.exists() and not venv_is_usable():
        if not VENV_DIR.is_dir():
            fail(f"repo-local virtualenv path is not a directory: {VENV_DIR}")
        log(f"recreating invalid repo-local Python virtual environment: {VENV_DIR}")
        shutil.rmtree(VENV_DIR)
    if not VENV_PYTHON.exists():
        create_venv()
    if not venv_is_usable():
        fail(f"failed to create an isolated repo-local Python virtual environment: {VENV_DIR}")
    run(
        [VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "west"],
        cwd=COMMON_MCU_DIR,
        env=local_env(),
    )


def create_venv() -> None:
    require_commands("uv")
    run(
        ["uv", "venv", "--python", VENV_PYTHON_VERSION, "--seed", VENV_DIR],
        cwd=COMMON_MCU_DIR,
        env=local_env(),
    )


def venv_is_usable() -> bool:
    if not VENV_PYTHON.exists():
        return False
    expected_prefix = repr(str(VENV_DIR.resolve()))
    check = (
        "import importlib.util, sys; from pathlib import Path; "
        f"expected = Path({expected_prefix}); "
        "raise SystemExit(0 if "
        "sys.prefix != sys.base_prefix and "
        "Path(sys.prefix).resolve() == expected and "
        f"sys.version_info[:2] == {tuple(map(int, VENV_PYTHON_VERSION.split('.')))!r} and "
        "importlib.util.find_spec('pip') is not None else 1)"
    )
    completed = subprocess.run(
        [str(VENV_PYTHON), "-c", check],
        cwd=COMMON_MCU_DIR,
        env=local_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return completed.returncode == 0


def ensure_zephyr_revision() -> None:
    if not ZEPHYR_BASE.is_dir():
        return
    status = run(
        ["git", "status", "--porcelain"],
        cwd=ZEPHYR_BASE,
        env=local_env(),
        capture=True,
    ).stdout.strip()
    if status:
        fail(f"refusing to switch dirty Zephyr checkout: {ZEPHYR_BASE}")

    if ZEPHYR_VERSION == "main":
        run(["git", "fetch", "origin", "main"], cwd=ZEPHYR_BASE, env=local_env())
        branch = run(
            ["git", "branch", "--list", "main"],
            cwd=ZEPHYR_BASE,
            env=local_env(),
            capture=True,
        ).stdout.strip()
        if branch:
            run(["git", "checkout", "main"], cwd=ZEPHYR_BASE, env=local_env())
        else:
            run(
                ["git", "checkout", "-b", "main", "origin/main"],
                cwd=ZEPHYR_BASE,
                env=local_env(),
            )
        run(["git", "pull", "--ff-only", "origin", "main"], cwd=ZEPHYR_BASE, env=local_env())
    else:
        run(["git", "fetch", "origin", "--tags"], cwd=ZEPHYR_BASE, env=local_env())
        run(["git", "checkout", ZEPHYR_VERSION], cwd=ZEPHYR_BASE, env=local_env())


def west_command() -> list[Path]:
    if not WEST_BIN.exists():
        fail("missing repo-local west. Run: just mcu::install")
    return [WEST_BIN]


def pyocd_bin() -> Path:
    return VENV_DIR / "bin" / "pyocd"


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
    ensure_zephyr_revision()
    run(
        west_command() + ["update", "--narrow", "--fetch-opt=--filter=blob:none"],
        cwd=WORKSPACE_DIR,
        env=local_env(),
    )
    ensure_zephyr_revision()
    run(west_command() + ["manifest", "--validate"], cwd=WORKSPACE_DIR, env=local_env())


def install_python_requirements() -> None:
    requirements = [
        ZEPHYR_BASE / "scripts" / "requirements-base.txt",
        ZEPHYR_BASE / "scripts" / "requirements-build-test.txt",
        ZEPHYR_BASE / "scripts" / "requirements-run-test.txt",
    ]
    for requirement in requirements:
        if not requirement.exists():
            fail(f"missing Zephyr Python requirements file: {requirement}")
    args: list[str | Path] = [VENV_PYTHON, "-m", "pip", "install", "--upgrade"]
    for requirement in requirements:
        args.extend(["-r", requirement])
    run(args, cwd=COMMON_MCU_DIR, env=local_env())


def install_pyocd_packs() -> None:
    if not pyocd_bin().exists():
        fail("missing repo-local pyOCD after installing Zephyr requirements")
    for pack in PYOCD_PACK_TARGETS:
        run(
            [pyocd_bin(), "pack", "install", "--update", pack],
            cwd=COMMON_MCU_DIR,
            env=local_env(),
        )
    require_pyocd_targets()


def ensure_power_si_blobs() -> None:
    missing = [path for path in POWER_SI_REQUIRED_BLOBS if not path.exists()]
    if not missing:
        return
    log("fetching Zephyr hal_silabs blobs required for power-si radio build")
    run(
        west_command()
        + ["blobs", "-a", "-l", POWER_SI_BLOB_REGEX, "fetch", "hal_silabs"],
        cwd=WORKSPACE_DIR,
        env=local_env(),
    )
    missing = [path for path in POWER_SI_REQUIRED_BLOBS if not path.exists()]
    if missing:
        fail(
            "missing power-si Zephyr blob(s) after fetch: "
            + ", ".join(str(path) for path in missing)
        )


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def build_profile(device: str, *, profile: str = "release", debug: bool = False) -> BuildProfile:
    if debug:
        if profile != "release":
            fail("--debug cannot be combined with --profile")
        profile = "debug"
    try:
        selected = BUILD_PROFILES[profile]
    except KeyError:
        fail(
            f"unsupported MCU build profile: {profile}. "
            f"Supported profiles: {', '.join(ACTIVE_BUILD_PROFILES)}"
        )
    if device == "power-si" and selected.name == "release":
        selected = POWER_SI_RELEASE_PROFILE
    if device in ("power-nrf", "tbot") and selected.name == "release":
        selected = POWER_NRF_RELEASE_PROFILE
    if device in ("power-nrf", "tbot") and selected.name == "sed-debug":
        selected = POWER_NRF_SED_DEBUG_PROFILE
    if selected.use_silabs_ccm_candidate and device != "power-si":
        fail(f"{selected.name} is only supported for power-si")
    return selected


def checkout_status(checkout: Path) -> str:
    return run(
        ["git", "status", "--porcelain"],
        cwd=checkout,
        env=local_env(),
        capture=True,
    ).stdout.strip()


def isolated_patches_for_device(
    device: str, *, profile: str = "release", debug: bool = False
) -> tuple[IsolatedPatch, ...]:
    selected = build_profile(device, profile=profile, debug=debug)
    patches: list[IsolatedPatch] = []
    if device == "power-si" and (
        selected.use_silabs_ccm_candidate
        or env_flag(POWER_SI_SILABS_CCM_PATCH_ENV)
    ):
        patches.extend(POWER_SI_SILABS_CCM_PATCHES)
    return tuple(patches)


@contextmanager
def applied_isolated_patches(patches: tuple[IsolatedPatch, ...]):
    if not patches:
        yield
        return

    for patch in patches:
        if not patch.checkout.is_dir():
            fail(f"missing isolated patch checkout: {patch.checkout}")
        if not patch.patch.exists():
            fail(f"missing isolated patch: {patch.patch}")

    checked_roots: set[Path] = set()
    for patch in patches:
        if patch.checkout in checked_roots:
            continue
        checked_roots.add(patch.checkout)
        status = checkout_status(patch.checkout)
        if status:
            fail(
                "refusing to apply isolated patch to dirty checkout: "
                f"{patch.checkout}. Clean the checkout or reverse any interrupted patch first."
            )

    log("applying isolated build patch(es); stock sources remain unchanged after the build")
    applied: list[IsolatedPatch] = []
    try:
        for patch in patches:
            run(
                ["git", "apply", "--check", patch.patch],
                cwd=patch.checkout,
                env=local_env(),
            )
            run(["git", "apply", patch.patch], cwd=patch.checkout, env=local_env())
            applied.append(patch)
        yield
    finally:
        log("reversing isolated build patch(es)")
        for patch in reversed(applied):
            reverse_check = subprocess.run(
                ["git", "apply", "--reverse", "--check", str(patch.patch)],
                cwd=patch.checkout,
                env=local_env(),
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if reverse_check.returncode == 0:
                run(["git", "apply", "--reverse", patch.patch], cwd=patch.checkout, env=local_env())
            else:
                fail(f"could not reverse isolated patch automatically: {patch.patch}")

        for checkout in checked_roots:
            status = checkout_status(checkout)
            if status:
                fail(f"checkout is dirty after reversing isolated patch: {checkout}")


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
    expected_ref = f"origin/{ZEPHYR_VERSION}" if ZEPHYR_VERSION == "main" else ZEPHYR_VERSION
    expected = run(
        ["git", "rev-list", "-n", "1", expected_ref],
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
    install_pyocd_packs()


def check() -> None:
    require_commands(
        "git",
        "python3",
        "cmake",
        "ninja",
        "dtc",
        "arm-none-eabi-gcc",
    )
    require_host_openocd()
    verify_workspace()
    if not NRF_OPENOCD_CFG.exists():
        fail(f"missing stock Zephyr Seeed OpenOCD config: {NRF_OPENOCD_CFG}. Run: just mcu::install")
    require_pyocd()
    require_pyocd_targets()
    if not BOARD_CONF.exists():
        fail(f"missing shared XIAO nRF54L15 board config: {BOARD_CONF}")
    if not NVE_SCRIPT.exists():
        fail(f"missing REDCON NVE script: {NVE_SCRIPT}")
    if not THREAD_FACTORY_SCRIPT.exists():
        fail(f"missing power-si TXT1 factory script: {THREAD_FACTORY_SCRIPT}")
    if not POWER_NRF_FACTORY_SCRIPT.exists():
        fail(f"missing nRF54LM20A TXN1 factory script: {POWER_NRF_FACTORY_SCRIPT}")
    if not (ZEPHYR_BASE / "boards" / "seeed" / "xiao_mg24").is_dir():
        fail("missing stock Zephyr Seeed XIAO MG24 board support. Run: just mcu::install")
    if not (ZEPHYR_BASE / "boards" / "seeed" / "xiao_nrf54lm20a").is_dir():
        fail("missing stock Zephyr XIAO nRF54LM20A board support. Run: just mcu::install")
    if not POWER_NRF_OPENOCD_CFG.exists():
        fail(
            "missing stock Zephyr XIAO nRF54LM20A OpenOCD config: "
            f"{POWER_NRF_OPENOCD_CFG}. Run: just mcu::install"
        )
    log(
        "ok: shared MCU toolchain, Zephyr workspace, nRF OpenOCD config, "
        "pyOCD packs, board config, NVE script, XIAO MG24 board support, "
        "XIAO nRF54LM20A board support, TXT1 factory script, and TXN1 factory script "
        "are available"
    )


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


def device_config(device: str) -> DeviceConfig:
    try:
        return DEVICE_CONFIGS[device]
    except KeyError:
        fail(
            f"unsupported MCU device type: {device}. "
            f"Supported device types: {', '.join(ACTIVE_DEVICES)}"
        )


def prj_conf(device: str) -> Path:
    return app_dir(device) / "prj.conf"


def overlay_file(device: str) -> Path:
    if device in ("power-nrf", "tbot"):
        return (
            COMMON_MCU_DIR
            / "xiao_nrf54lm20a"
            / "boards"
            / device_config(device).overlay_name
        )
    return app_dir(device) / "boards" / device_config(device).overlay_name


def build_dir(device: str, *, debug: bool = False, profile: str = "release") -> Path:
    selected = build_profile(device, profile=profile, debug=debug)
    build_name = f"{device_config(device).build_name}{selected.build_suffix}"
    return device_mcu_dir(device) / "build" / build_name


def firmware_candidates(
    device: str, *, debug: bool = False, profile: str = "release"
) -> tuple[Path, Path]:
    directory = build_dir(device, debug=debug, profile=profile)
    return (
        directory / "zephyr" / "zephyr.hex",
        directory / "zephyr" / "zephyr" / "zephyr.hex",
    )


def firmware_hex(device: str, *, debug: bool = False, profile: str = "release") -> Path:
    candidates = firmware_candidates(device, debug=debug, profile=profile)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def build_command_for_profile(profile: str) -> str:
    if profile == "release":
        return "build"
    return f"build-{profile}"


def require_firmware_hex(
    device: str, *, debug: bool = False, profile: str = "release"
) -> Path:
    selected = build_profile(device, profile=profile, debug=debug)
    candidate = firmware_hex(device, profile=selected.name)
    if not candidate.exists():
        fail(
            "missing firmware hex. Run: "
            f"just {device}::mcu::{build_command_for_profile(selected.name)}"
        )
    return candidate


def pristine_mode(device: str, *, profile: str = "release") -> str:
    cache = build_dir(device, profile=profile) / "CMakeCache.txt"
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


def build(device: str, *, debug: bool = False, profile: str = "release") -> None:
    require_commands("git", "python3", "cmake", "ninja", "dtc", "arm-none-eabi-gcc")
    verify_workspace()
    if device == "power-si":
        ensure_power_si_blobs()
    selected = build_profile(device, profile=profile, debug=debug)
    config = device_config(device)
    conf = prj_conf(device)
    overlay = overlay_file(device)
    required_inputs = [conf, overlay]
    extra_conf_files = []
    if config.extra_conf is not None:
        extra_conf_files.append(config.extra_conf)
    if selected.debug_conf:
        if config.debug_conf is None:
            fail(f"{device} does not have a debug MCU build profile")
        extra_conf_files.append(config.debug_conf)
    if selected.sed_debug_conf:
        if config.sed_debug_conf is None:
            fail(f"{device} does not have an SED debug MCU build profile")
        extra_conf_files.append(config.sed_debug_conf)
    if selected.release_conf:
        if config.release_conf is None:
            fail(f"{device} does not have a release MCU build overlay")
        extra_conf_files.append(config.release_conf)
    required_inputs.extend(extra_conf_files)
    for path in required_inputs:
        if not path.exists():
            fail(f"missing build input: {path}")
    cmake_args: list[str | Path] = [
        f"-DCONF_FILE={conf}",
        f"-DDTC_OVERLAY_FILE={overlay}",
        f"-DBUILD_VERSION={BUILD_VERSION}",
    ]
    if extra_conf_files:
        cmake_args.append(
            "-DEXTRA_CONF_FILE=" + ";".join(str(path) for path in extra_conf_files)
        )
    with applied_isolated_patches(
        isolated_patches_for_device(device, profile=selected.name)
    ):
        run(
            west_command()
            + [
                "-z",
                ZEPHYR_BASE,
                "build",
                "-p",
                (
                    "always"
                    if selected.force_pristine
                    else pristine_mode(device, profile=selected.name)
                ),
                "-b",
                config.board,
                app_dir(device),
                "-d",
                build_dir(device, profile=selected.name),
                "--",
            ]
            + cmake_args,
            cwd=WORKSPACE_DIR,
            env=local_env(),
        )
    hex_file = firmware_hex(device, profile=selected.name)
    if not hex_file.exists():
        fail(f"build completed, but no expected firmware HEX was created: {hex_file}")
    log(f"ok: built {hex_file}")


def clean(device: str) -> None:
    for profile in ACTIVE_BUILD_PROFILES:
        if profile == "sed-debug" and device not in ("power-si", "power-nrf", "tbot"):
            continue
        path = build_dir(device, profile=profile)
        if path.exists():
            log(f"removing {path}")
            shutil.rmtree(path)


def openocd_program() -> str:
    return "openocd"


def require_host_openocd() -> None:
    if shutil.which(openocd_program()) is None:
        fail("missing OpenOCD. Install OpenOCD and make sure openocd is on PATH")


def require_pyocd() -> None:
    if not pyocd_bin().exists():
        fail("missing repo-local pyOCD. Run: just mcu::install")


def require_pyocd_targets() -> None:
    require_pyocd()
    completed = run(
        [pyocd_bin(), "list", "--targets"],
        cwd=COMMON_MCU_DIR,
        env=local_env(),
        capture=True,
    )
    output = completed.stdout
    missing = [
        target for target in PYOCD_REQUIRED_TARGETS if target.lower() not in output.lower()
    ]
    if missing:
        fail(
            "missing pyOCD CMSIS target pack(s): "
            + ", ".join(missing)
            + ". Run: just mcu::install and confirm pyocd pack install "
            + "EFR32MG24B220F1536IM48 succeeds"
        )


def nrf_openocd_command(hex_file: Path) -> list[str | Path]:
    return [
        openocd_program(),
        "-s",
        NRF_OPENOCD_SUPPORT_DIR,
        "-f",
        NRF_OPENOCD_CFG,
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


def power_nrf_openocd_command(hex_file: Path) -> list[str | Path]:
    return [
        openocd_program(),
        "-s",
        POWER_NRF_OPENOCD_SUPPORT_DIR,
        "-f",
        POWER_NRF_OPENOCD_CFG,
        "-c",
        "init",
        "-c",
        "targets nrf54lm20a.cpu",
        "-c",
        "reset init",
        "-c",
        f"nrf54lm20a-load {hex_file}",
        "-c",
        f"verify_image {hex_file}",
        "-c",
        "reset run",
        "-c",
        "shutdown",
    ]


def openocd_command(device: str, hex_file: Path) -> list[str | Path]:
    runner = device_config(device).flash_runner
    if runner == "openocd-nrf54l15":
        return nrf_openocd_command(hex_file)
    if runner == "openocd-nrf54lm20a":
        return power_nrf_openocd_command(hex_file)
    fail(f"{device} does not have an automated OpenOCD flash recipe")


def require_openocd(device: str) -> None:
    verify_workspace()
    runner = device_config(device).flash_runner
    require_host_openocd()
    if runner == "openocd-nrf54l15" and not NRF_OPENOCD_CFG.exists():
        fail(f"missing stock Zephyr Seeed OpenOCD config: {NRF_OPENOCD_CFG}. Run: just mcu::install")
    if runner == "openocd-nrf54lm20a" and not POWER_NRF_OPENOCD_CFG.exists():
        fail(
            "missing stock Zephyr XIAO nRF54LM20A OpenOCD config: "
            f"{POWER_NRF_OPENOCD_CFG}. Run: just mcu::install"
        )


def run_openocd(device: str, hex_file: Path) -> None:
    require_openocd(device)
    run(openocd_command(device, hex_file), cwd=PROJECT_ROOT, env=local_env())


def west_flash_command(
    device: str,
    hex_file: Path | None = None,
    *,
    debug: bool = False,
    profile: str = "release",
) -> list[str | Path]:
    selected = build_profile(device, profile=profile, debug=debug)
    command: list[str | Path] = [
        *west_command(),
        "flash",
        "--no-rebuild",
        "-d",
        build_dir(device, profile=selected.name),
        "-r",
        "pyocd",
        "--",
        "--pyocd",
        pyocd_bin(),
    ]
    if hex_file is not None:
        command.extend(["--hex-file", hex_file])
    return command


def run_west_flash(
    device: str,
    hex_file: Path | None = None,
    *,
    debug: bool = False,
    profile: str = "release",
) -> None:
    selected = build_profile(device, profile=profile, debug=debug)
    verify_workspace()
    require_pyocd_targets()
    run(
        west_flash_command(device, hex_file, profile=selected.name),
        cwd=WORKSPACE_DIR,
        env=local_env(),
    )


def flash(device: str, *, debug: bool = False, profile: str = "release") -> None:
    selected = build_profile(device, profile=profile, debug=debug)
    hex_file = require_firmware_hex(device, profile=selected.name)
    runner = device_config(device).flash_runner
    if runner == "openocd-nrf54l15":
        run_openocd(device, hex_file)
        return
    if runner == "openocd-nrf54lm20a":
        run_openocd(device, hex_file)
        return
    if runner == "west-pyocd":
        run_west_flash(device, hex_file, profile=selected.name)
        return
    fail(f"{device} does not have an automated flash recipe")


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


def nrf_nve(thing_name: str) -> None:
    build_nve_hex(thing_name)
    run_openocd("power", NVE_HEX)


def build_thread_factory_hex(
    thing_name: str, dataset_tlvs: Path, output: Path | None, port: int
) -> None:
    if not THREAD_FACTORY_SCRIPT.exists():
        fail(f"missing power-si TXT1 factory script: {THREAD_FACTORY_SCRIPT}")
    factory_hex = output or POWER_SI_FACTORY_HEX
    factory_hex.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            sys.executable,
            THREAD_FACTORY_SCRIPT,
            "write-hex",
            thing_name,
            "--dataset-tlvs",
            dataset_tlvs,
            "--port",
            str(port),
            "--output",
            factory_hex,
        ],
        cwd=PROJECT_ROOT,
        env=local_env(),
    )


def power_si_nve(thing_name: str, dataset_tlvs: Path, port: int) -> None:
    build_thread_factory_hex(thing_name, dataset_tlvs, POWER_SI_FACTORY_HEX, port)
    run_west_flash("power-si", POWER_SI_FACTORY_HEX)


def build_lm20a_thread_factory_hex(
    device: str, thing_name: str, dataset_tlvs: Path, output: Path | None, port: int
) -> None:
    if not POWER_NRF_FACTORY_SCRIPT.exists():
        fail(f"missing nRF54LM20A TXN1 factory script: {POWER_NRF_FACTORY_SCRIPT}")
    default_output = POWER_NRF_FACTORY_HEX if device == "power-nrf" else TBOT_FACTORY_HEX
    factory_hex = output or default_output
    factory_hex.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            sys.executable,
            POWER_NRF_FACTORY_SCRIPT,
            "write-hex",
            thing_name,
            "--dataset-tlvs",
            dataset_tlvs,
            "--port",
            str(port),
            "--output",
            factory_hex,
        ],
        cwd=PROJECT_ROOT,
        env=local_env(),
    )


def lm20a_thread_nve(device: str, thing_name: str, dataset_tlvs: Path, port: int) -> None:
    factory_hex = POWER_NRF_FACTORY_HEX if device == "power-nrf" else TBOT_FACTORY_HEX
    build_lm20a_thread_factory_hex(device, thing_name, dataset_tlvs, factory_hex, port)
    run_openocd(device, factory_hex)


def nve(device: str | None, thing_name: str, dataset_tlvs: Path | None, port: int) -> None:
    if device in ("power-nrf", "tbot"):
        if dataset_tlvs is None:
            fail(f"{device} nve requires <thing-name> <dataset-tlvs-file>")
        lm20a_thread_nve(device, thing_name, dataset_tlvs, port)
        return
    if device not in (None, "power-si"):
        fail("nve supports power-nrf, tbot, or the existing TXR1/TXT1 command forms")
    if dataset_tlvs is None:
        nrf_nve(thing_name)
        return
    power_si_nve(thing_name, dataset_tlvs, port)


def require_device(command: str, device: str | None) -> str:
    if device is None:
        fail(f"{command} requires --device <device-type>")
    return device


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage txing MCU builds with shared stock Zephyr."
    )
    parser.add_argument("--device", choices=ACTIVE_DEVICES)
    parser.add_argument("--output", type=Path, help="output path for generated factory HEX")
    parser.add_argument("--port", type=int, default=5683, help="CoAP port for Thread factory data")
    parser.add_argument(
        "--profile",
        choices=ACTIVE_BUILD_PROFILES,
        default="release",
        help="firmware build/flash profile",
    )
    parser.add_argument("--debug", action="store_true", help="legacy alias for --profile debug")
    parser.add_argument(
        "command",
        choices=(
            "install",
            "check",
            "build",
            "build-debug",
            "build-sed-debug",
            "clean",
            "flash",
            "nve",
            "thread-factory-hex",
        ),
    )
    parser.add_argument("thing_name", nargs="?")
    parser.add_argument("dataset_tlvs", nargs="?")
    args = parser.parse_args()

    if args.debug and args.command != "flash":
        fail("--debug is only supported with flash")
    if args.debug and args.profile != "release":
        fail("--debug cannot be combined with --profile")

    if args.command == "install":
        install()
    elif args.command == "check":
        if args.device:
            fail("mcu check is shared and does not take --device")
        check()
    elif args.command == "build":
        if args.profile != "release":
            fail("--profile is only supported with flash; use build-* commands for builds")
        build(require_device(args.command, args.device))
    elif args.command == "build-debug":
        if args.profile != "release":
            fail("--profile is only supported with flash; use build-* commands for builds")
        build(require_device(args.command, args.device), profile="debug")
    elif args.command == "build-sed-debug":
        if args.profile != "release":
            fail("--profile is only supported with flash; use build-* commands for builds")
        build(require_device(args.command, args.device), profile="sed-debug")
    elif args.command == "clean":
        clean(require_device(args.command, args.device))
    elif args.command == "flash":
        flash(require_device(args.command, args.device), debug=args.debug, profile=args.profile)
    elif args.command == "nve":
        if args.thing_name is None:
            fail("nve requires <thing-name>")
        nve(
            args.device,
            args.thing_name,
            Path(args.dataset_tlvs) if args.dataset_tlvs is not None else None,
            args.port,
        )
    elif args.command == "thread-factory-hex":
        device = require_device(args.command, args.device)
        if device not in ("power-si", "power-nrf", "tbot"):
            fail("thread-factory-hex is only supported for --device power-si, power-nrf, or tbot")
        if args.thing_name is None or args.dataset_tlvs is None:
            fail("thread-factory-hex requires <thing-name> <dataset-tlvs-file>")
        if device == "power-si":
            build_thread_factory_hex(
                args.thing_name,
                Path(args.dataset_tlvs),
                args.output,
                args.port,
            )
        else:
            build_lm20a_thread_factory_hex(
                device,
                args.thing_name,
                Path(args.dataset_tlvs),
                args.output,
                args.port,
            )


if __name__ == "__main__":
    main()
