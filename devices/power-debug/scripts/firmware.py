#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import shlex
import subprocess
import venv
from pathlib import Path


POWER_DEBUG_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = POWER_DEBUG_DIR.parents[1]
COMMON_MCU_DIR = PROJECT_ROOT / "devices" / "common" / "mcu"
ENV_NAME = "seeed-xiao-nrf54l15"

VENV_DIR = POWER_DEBUG_DIR / ".venv"
PIO_CORE_DIR = POWER_DEBUG_DIR / ".platformio-core"
PIO_HOME_DIR = POWER_DEBUG_DIR / ".home"
PIO_BUILD_DIR = POWER_DEBUG_DIR / ".pio" / "build" / ENV_NAME
PIP_CACHE_DIR = POWER_DEBUG_DIR / ".pip-cache"
PIO_TOOLCHAIN_DIR = PIO_CORE_DIR / "packages" / "toolchain-gccarmnoneeabi"

NATIVE_VENV_DIR = POWER_DEBUG_DIR / ".native-venv"
NATIVE_PIP_CACHE_DIR = POWER_DEBUG_DIR / ".native-pip-cache"
NATIVE_ZEPHYR_CACHE_DIR = POWER_DEBUG_DIR / ".native-zephyr-cache"
NATIVE_CCACHE_DIR = POWER_DEBUG_DIR / ".native-ccache"
NATIVE_ZEPHYR_BASE = COMMON_MCU_DIR / "zephyr"
NATIVE_SEEED_PLATFORM = COMMON_MCU_DIR / "seeed-platform"
NATIVE_BOARD_ROOT = NATIVE_SEEED_PLATFORM / "zephyr"
NATIVE_BOARD_DIR = NATIVE_BOARD_ROOT / "boards" / "arm" / "xiao_nrf54l15"
NATIVE_OPENOCD_SUPPORT_DIR = NATIVE_BOARD_DIR / "support"
NATIVE_OPENOCD_CFG = NATIVE_OPENOCD_SUPPORT_DIR / "openocd.cfg"
NATIVE_BUILD_DIR = POWER_DEBUG_DIR / "build" / "zephyr-xiao_nrf54l15_cpuapp"
BREW_BUILD_DIR = POWER_DEBUG_DIR / "build" / "zephyr-xiao_nrf54l15_cpuapp-brew"
NATIVE_TOOLCHAIN_DIR = COMMON_MCU_DIR / "toolchain-gccarmnoneeabi"
NATIVE_BOARD = "xiao_nrf54l15/nrf54l15/cpuapp"
NATIVE_BUILD_VERSION = "zephyr-v40201"
BREW_BUILD_VERSION = "zephyr-v40201-brew"
NATIVE_REQUIRED_GCC = "8.2.1"
NATIVE_SUBMODULE_PATHS = [
	COMMON_MCU_DIR / "zephyr",
	COMMON_MCU_DIR / "seeed-platform",
	COMMON_MCU_DIR / "modules" / "hal" / "nordic",
	COMMON_MCU_DIR / "modules" / "hal" / "cmsis",
	COMMON_MCU_DIR / "modules" / "hal" / "cmsis_6",
	COMMON_MCU_DIR / "modules" / "lib" / "picolibc",
]
NATIVE_ZEPHYR_MODULES = [
	COMMON_MCU_DIR / "modules" / "hal" / "cmsis",
	COMMON_MCU_DIR / "modules" / "hal" / "cmsis_6",
	COMMON_MCU_DIR / "modules" / "hal" / "nordic",
	COMMON_MCU_DIR / "modules" / "lib" / "picolibc",
]

PLATFORMIO_INI = POWER_DEBUG_DIR / "platformio.ini"
FIRMWARE_ELF = PIO_BUILD_DIR / "firmware.elf"
FIRMWARE_HEX = PIO_BUILD_DIR / "firmware.hex"
NATIVE_FIRMWARE_ELF = NATIVE_BUILD_DIR / "zephyr" / "zephyr.elf"
NATIVE_FIRMWARE_HEX = NATIVE_BUILD_DIR / "zephyr" / "zephyr.hex"
BREW_FIRMWARE_ELF = BREW_BUILD_DIR / "zephyr" / "zephyr.elf"
BREW_FIRMWARE_HEX = BREW_BUILD_DIR / "zephyr" / "zephyr.hex"
PIO_OPENOCD = PIO_CORE_DIR / "packages" / "tool-openocd" / "bin" / "openocd"
PIO_OPENOCD_SCRIPTS = PIO_CORE_DIR / "packages" / "tool-openocd" / "openocd" / "scripts"


def venv_python() -> Path:
	if os.name == "nt":
		return VENV_DIR / "Scripts" / "python.exe"
	return VENV_DIR / "bin" / "python"


def pio_executable() -> Path:
	if os.name == "nt":
		return VENV_DIR / "Scripts" / "pio.exe"
	return VENV_DIR / "bin" / "pio"


def native_python() -> Path:
	if os.name == "nt":
		return NATIVE_VENV_DIR / "Scripts" / "python.exe"
	return NATIVE_VENV_DIR / "bin" / "python"


def env() -> dict[str, str]:
	local = os.environ.copy()
	local["HOME"] = str(PIO_HOME_DIR)
	local["PIP_CACHE_DIR"] = str(PIP_CACHE_DIR)
	local["PLATFORMIO_CORE_DIR"] = str(PIO_CORE_DIR)
	local["PLATFORMIO_FORCE_COLOR"] = "0"
	local["PLATFORMIO_SETTING_CHECK_LIBRARIES_INTERVAL"] = "0"
	local["PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL"] = "0"
	local["PLATFORMIO_SETTING_CHECK_PLATFORMS_INTERVAL"] = "0"
	local["PLATFORMIO_SETTING_ENABLE_TELEMETRY"] = "No"
	local["PATH"] = f"{pio_executable().parent}{os.pathsep}{local.get('PATH', '')}"
	return local


def native_toolchain_dir() -> Path:
	configured = os.environ.get("GNUARMEMB_TOOLCHAIN_PATH")
	if configured:
		return Path(configured).resolve()
	if NATIVE_TOOLCHAIN_DIR.exists():
		return NATIVE_TOOLCHAIN_DIR.resolve()
	if PIO_TOOLCHAIN_DIR.exists():
		return PIO_TOOLCHAIN_DIR.resolve()
	return NATIVE_TOOLCHAIN_DIR.resolve()


def require_repo_local_path(label: str, path: Path) -> Path:
	resolved = path.resolve()
	try:
		resolved.relative_to(PROJECT_ROOT)
	except ValueError:
		raise SystemExit(
			f"{label} must live inside this repository.\n"
			f"Got: {resolved}\n"
			f"Expected a path under: {PROJECT_ROOT}"
		) from None
	return resolved


def native_openocd_executable() -> Path:
	configured = os.environ.get("POWER_DEBUG_OPENOCD")
	if configured:
		openocd = require_repo_local_path("POWER_DEBUG_OPENOCD", Path(configured))
	elif PIO_OPENOCD.exists():
		openocd = PIO_OPENOCD.resolve()
	else:
		raise SystemExit(
			"missing repo-local OpenOCD for native power-debug flash.\n"
			f"Expected: {PIO_OPENOCD}\n"
			"Run `just power-debug::firmware-install`, or set POWER_DEBUG_OPENOCD "
			"to a repo-local OpenOCD binary."
		)
	if not openocd.exists():
		raise SystemExit(f"missing OpenOCD executable: {openocd}")
	return openocd


def native_openocd_scripts_dir() -> Path:
	configured = os.environ.get("POWER_DEBUG_OPENOCD_SCRIPTS")
	if configured:
		scripts = require_repo_local_path("POWER_DEBUG_OPENOCD_SCRIPTS", Path(configured))
	else:
		scripts = PIO_OPENOCD_SCRIPTS.resolve()
	if not scripts.exists():
		raise SystemExit(
			"missing repo-local OpenOCD scripts directory.\n"
			f"Expected: {scripts}\n"
			"Set POWER_DEBUG_OPENOCD_SCRIPTS to a repo-local OpenOCD scripts path."
		)
	if not (scripts / "interface" / "cmsis-dap.cfg").exists():
		raise SystemExit(f"OpenOCD scripts path does not contain interface/cmsis-dap.cfg: {scripts}")
	return scripts


def native_env() -> dict[str, str]:
	local = os.environ.copy()
	toolchain = native_toolchain_dir()
	path_entries = [
		str(native_python().parent),
		str(toolchain / "bin"),
		local.get("PATH", ""),
	]
	local["PIP_CACHE_DIR"] = str(NATIVE_PIP_CACHE_DIR)
	local["POWER_DEBUG_BOARD_ROOT"] = str(NATIVE_BOARD_ROOT)
	local["CCACHE_DIR"] = str(NATIVE_CCACHE_DIR)
	local["CCACHE_DISABLE"] = "1"
	local["ZEPHYR_CACHE_DIR"] = str(NATIVE_ZEPHYR_CACHE_DIR)
	local["ZEPHYR_BASE"] = str(NATIVE_ZEPHYR_BASE)
	local["ZEPHYR_TOOLCHAIN_VARIANT"] = "gnuarmemb"
	local["GNUARMEMB_TOOLCHAIN_PATH"] = str(toolchain)
	local["PATH"] = os.pathsep.join(part for part in path_entries if part)
	return local


def brew_cross_compile_prefix() -> str:
	configured = os.environ.get("POWER_DEBUG_BREW_CROSS_COMPILE") or os.environ.get("CROSS_COMPILE")
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


def brew_tool_path(name: str) -> Path:
	return Path(brew_cross_compile_prefix() + name)


def brew_env() -> dict[str, str]:
	local = os.environ.copy()
	prefix = brew_cross_compile_prefix()
	path_entries = [
		str(native_python().parent),
		str(Path(prefix + "gcc").parent),
		local.get("PATH", ""),
	]
	local["PIP_CACHE_DIR"] = str(NATIVE_PIP_CACHE_DIR)
	local["POWER_DEBUG_BOARD_ROOT"] = str(NATIVE_BOARD_ROOT)
	local["CCACHE_DIR"] = str(NATIVE_CCACHE_DIR)
	local["CCACHE_DISABLE"] = "1"
	local["ZEPHYR_CACHE_DIR"] = str(NATIVE_ZEPHYR_CACHE_DIR)
	local["ZEPHYR_BASE"] = str(NATIVE_ZEPHYR_BASE)
	local["ZEPHYR_TOOLCHAIN_VARIANT"] = "cross-compile"
	local["CROSS_COMPILE"] = prefix
	local.pop("GNUARMEMB_TOOLCHAIN_PATH", None)
	local["PATH"] = os.pathsep.join(part for part in path_entries if part)
	return local


def run(
	args: list[str | Path],
	*,
	cwd: Path = POWER_DEBUG_DIR,
	command_env: dict[str, str] | None = None,
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
		env=command_env if command_env is not None else env(),
		text=True,
		check=check,
		capture_output=capture_output,
	)


def ensure_local_dirs() -> None:
	for path in (PIO_HOME_DIR, PIO_CORE_DIR, PIP_CACHE_DIR):
		path.mkdir(parents=True, exist_ok=True)


def install() -> None:
	ensure_local_dirs()
	if not venv_python().exists():
		print(f"creating local venv: {VENV_DIR}", flush=True)
		venv.EnvBuilder(with_pip=True).create(VENV_DIR)

	run([venv_python(), "-m", "pip", "install", "--upgrade", "pip", "platformio"])
	run([pio_executable(), "--version"])


def native_install() -> None:
	ensure_native_submodules_present()
	NATIVE_PIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
	NATIVE_ZEPHYR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
	NATIVE_CCACHE_DIR.mkdir(parents=True, exist_ok=True)
	if not native_python().exists():
		print(f"creating native Zephyr venv: {NATIVE_VENV_DIR}", flush=True)
		venv.EnvBuilder(with_pip=True).create(NATIVE_VENV_DIR)

	run(
		[
			native_python(),
			"-m",
			"pip",
			"install",
			"--upgrade",
			"pip",
			"-r",
			NATIVE_ZEPHYR_BASE / "scripts" / "requirements-base.txt",
		],
		command_env=native_env(),
	)
	run([native_python(), "-m", "west", "--version"], command_env=native_env())


def ensure_installed() -> None:
	if not pio_executable().exists():
		raise SystemExit(
			"missing repo-local PlatformIO. Run: just power-debug::firmware-install"
		)


def ensure_native_submodules_present() -> None:
	missing = [
		path
		for path in NATIVE_SUBMODULE_PATHS
		if not path.exists() or not any(path.iterdir())
	]
	if missing:
		paths = "\n".join(f"  - {path}" for path in missing)
		raise SystemExit(
			"missing native Zephyr submodules. Run:\n"
			"  just power-debug::firmware-native-submodules\n"
			"Missing paths:\n"
			f"{paths}"
		)


def ensure_native_installed() -> None:
	if not native_python().exists():
		raise SystemExit(
			"missing native Zephyr Python environment. Run: "
			"just power-debug::firmware-native-install"
		)
	ensure_native_submodules_present()
	ensure_native_toolchain()


def ensure_brew_installed() -> None:
	if not native_python().exists():
		raise SystemExit(
			"missing native Zephyr Python environment. Run: "
			"just power-debug::firmware-brew-install"
		)
	ensure_native_submodules_present()
	ensure_brew_toolchain()


def ensure_native_toolchain() -> None:
	toolchain = require_repo_local_path("native power-debug toolchain", native_toolchain_dir())
	gcc = toolchain / "bin" / "arm-none-eabi-gcc"
	if not gcc.exists():
		raise SystemExit(
			"missing GNU Arm Embedded toolchain for native power-debug build.\n"
			f"Expected: {gcc}\n"
			"Install GCC Arm Embedded 8.2.1 under "
			f"{NATIVE_TOOLCHAIN_DIR}, run `just power-debug::firmware-install` "
			"to use the repo-local PlatformIO package fallback, or set "
			"GNUARMEMB_TOOLCHAIN_PATH."
		)
	result = run(
		[gcc, "--version"],
		command_env=native_env(),
		check=False,
		capture_output=True,
	)
	first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
	if NATIVE_REQUIRED_GCC not in first_line:
		raise SystemExit(
			"native power-debug build requires the known-good GNU Arm Embedded "
			f"GCC {NATIVE_REQUIRED_GCC}; got: {first_line or 'unknown'}\n"
			"Set GNUARMEMB_TOOLCHAIN_PATH to the repo-local GCC 8.2.1 package. "
			"Do not use Homebrew/system GCC for the reproduction build."
		)


def ensure_brew_toolchain() -> None:
	prefix = brew_cross_compile_prefix()
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
			"Or set POWER_DEBUG_BREW_CROSS_COMPILE to a full prefix such as "
			"/opt/homebrew/bin/arm-none-eabi-\n"
			"Missing:\n"
			f"{paths}"
		)

	result = run(
		[gcc, "--version"],
		command_env=brew_env(),
		check=False,
		capture_output=True,
	)
	first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
	if "arm-none-eabi-gcc" not in first_line:
		raise SystemExit(
			"unexpected Homebrew compiler version output from "
			f"{gcc}: {first_line or 'unknown'}"
		)


def pio_run(target: str | None = None) -> None:
	ensure_installed()
	args: list[str | Path] = [pio_executable(), "run", "--environment", ENV_NAME]
	if target:
		args.extend(["--target", target])
	run(args)


def native_submodules() -> None:
	run(
		[
			"git",
			"submodule",
			"update",
			"--init",
			"--recursive",
			"--",
			*(str(path.relative_to(PROJECT_ROOT)) for path in NATIVE_SUBMODULE_PATHS),
		],
		cwd=PROJECT_ROOT,
		command_env=os.environ.copy(),
	)


def native_cmake_configure() -> None:
	ensure_native_installed()
	cmake_configure(
		build_dir=NATIVE_BUILD_DIR,
		build_version=NATIVE_BUILD_VERSION,
		toolchain_args=[],
		command_env=native_env(),
	)


def brew_cmake_configure() -> None:
	ensure_brew_installed()
	cmake_configure(
		build_dir=BREW_BUILD_DIR,
		build_version=BREW_BUILD_VERSION,
		toolchain_args=[
			"-DZEPHYR_TOOLCHAIN_VARIANT=cross-compile",
			f"-DCROSS_COMPILE={brew_cross_compile_prefix()}",
		],
		command_env=brew_env(),
	)


def cmake_configure(
	*,
	build_dir: Path,
	build_version: str,
	toolchain_args: list[str],
	command_env: dict[str, str],
) -> None:
	build_dir.mkdir(parents=True, exist_ok=True)
	module_arg = ";".join(str(path) for path in NATIVE_ZEPHYR_MODULES)
	run(
		[
			"cmake",
			"-S",
			POWER_DEBUG_DIR / "zephyr",
			"-B",
			build_dir,
			"-G",
			"Ninja",
			f"-DBOARD={NATIVE_BOARD}",
			f"-DBOARD_ROOT={NATIVE_BOARD_ROOT}",
			f"-DZEPHYR_MODULES={module_arg}",
			f"-DPython3_EXECUTABLE={native_python()}",
			f"-DPYTHON_EXECUTABLE={native_python()}",
			f"-DGEN_KOBJECT_LIST={NATIVE_ZEPHYR_BASE / 'scripts' / 'build' / 'gen_kobject_list.py'}",
			f"-DBUILD_VERSION={build_version}",
			f"-DUSER_CACHE_DIR={NATIVE_ZEPHYR_CACHE_DIR}",
			*toolchain_args,
			"-DUSE_CCACHE=0",
			"-DCCACHE_PROGRAM=CCACHE_PROGRAM-NOTFOUND",
			"-DCMAKE_C_COMPILER_LAUNCHER=",
			"-DCMAKE_CXX_COMPILER_LAUNCHER=",
		],
		command_env=command_env,
	)


def native_build() -> None:
	native_cmake_configure()
	run(
		["cmake", "--build", NATIVE_BUILD_DIR],
		command_env=native_env(),
	)


def brew_build() -> None:
	brew_cmake_configure()
	run(
		["cmake", "--build", BREW_BUILD_DIR],
		command_env=brew_env(),
	)


def native_flash() -> None:
	native_build()
	run(native_flash_openocd_command(), command_env=native_env())


def brew_flash() -> None:
	brew_build()
	run(brew_flash_openocd_command(), command_env=brew_env())


def native_flash_openocd_command() -> list[Path | str]:
	return flash_openocd_command(
		firmware_hex=NATIVE_FIRMWARE_HEX,
		build_command="just power-debug::firmware-native-check",
	)


def brew_flash_openocd_command() -> list[Path | str]:
	return flash_openocd_command(
		firmware_hex=BREW_FIRMWARE_HEX,
		build_command="just power-debug::firmware-brew-check",
	)


def flash_openocd_command(*, firmware_hex: Path, build_command: str) -> list[Path | str]:
	if not firmware_hex.exists():
		raise SystemExit(
			f"missing firmware hex. Run: {build_command}"
		)
	if not NATIVE_OPENOCD_CFG.exists():
		raise SystemExit(f"missing Seeed OpenOCD config: {NATIVE_OPENOCD_CFG}")
	openocd = native_openocd_executable()
	openocd_scripts = native_openocd_scripts_dir()
	return [
		openocd,
		"-s",
		openocd_scripts,
		"-s",
		NATIVE_OPENOCD_SUPPORT_DIR,
		"-f",
		NATIVE_OPENOCD_CFG,
		"-c",
		"init",
		"-c",
		"targets nrf54l.cpu",
		"-c",
		"reset init",
		"-c",
		f"nrf54l-load {firmware_hex}",
		"-c",
		f"verify_image {firmware_hex}",
		"-c",
		"reset run",
		"-c",
		"shutdown",
	]


def native_flash_command() -> None:
	ensure_native_installed()
	command = [str(part) for part in native_flash_openocd_command()]
	print(" ".join(shlex.quote(part) for part in command))


def brew_flash_command() -> None:
	ensure_brew_installed()
	command = [str(part) for part in brew_flash_openocd_command()]
	print(" ".join(shlex.quote(part) for part in command))


def clean() -> None:
	for path in (POWER_DEBUG_DIR / ".pio",):
		if path.exists():
			print(f"removing {path}", flush=True)
			shutil.rmtree(path)


def native_clean() -> None:
	if NATIVE_BUILD_DIR.exists():
		print(f"removing {NATIVE_BUILD_DIR}", flush=True)
		shutil.rmtree(NATIVE_BUILD_DIR)


def brew_clean() -> None:
	if BREW_BUILD_DIR.exists():
		print(f"removing {BREW_BUILD_DIR}", flush=True)
		shutil.rmtree(BREW_BUILD_DIR)


def print_path(label: str, path: Path) -> None:
	print(f"{label}: {path} exists={int(path.exists())}")


def paths() -> None:
	packages_dir = PIO_CORE_DIR / "packages"
	platforms_dir = PIO_CORE_DIR / "platforms"

	print(f"projectRoot: {PROJECT_ROOT}")
	print(f"deviceDir: {POWER_DEBUG_DIR}")
	print(f"env: {ENV_NAME}")
	print_path("platformioIni", PLATFORMIO_INI)
	print_path("venv", VENV_DIR)
	print_path("platformio", pio_executable())
	print_path("platformioCore", PIO_CORE_DIR)
	print_path("platformioHome", PIO_HOME_DIR)
	print_path("buildDir", PIO_BUILD_DIR)
	print_path("firmwareElf", FIRMWARE_ELF)
	print_path("firmwareHex", FIRMWARE_HEX)

	if platforms_dir.exists():
		for platform in sorted(platforms_dir.iterdir()):
			print_path("platform", platform)

	if packages_dir.exists():
		for package in sorted(packages_dir.iterdir()):
			if any(token in package.name.lower() for token in ("zephyr", "toolchain", "cmsis")):
				print_path("package", package)


def native_paths() -> None:
	print(f"projectRoot: {PROJECT_ROOT}")
	print(f"deviceDir: {POWER_DEBUG_DIR}")
	print(f"board: {NATIVE_BOARD}")
	print(f"buildVersion: {NATIVE_BUILD_VERSION}")
	print_path("nativeVenv", NATIVE_VENV_DIR)
	print_path("nativePython", native_python())
	print_path("nativePipCache", NATIVE_PIP_CACHE_DIR)
	print_path("nativeZephyrCache", NATIVE_ZEPHYR_CACHE_DIR)
	print_path("nativeCcache", NATIVE_CCACHE_DIR)
	print_path("zephyrBase", NATIVE_ZEPHYR_BASE)
	print_path("seeedPlatform", NATIVE_SEEED_PLATFORM)
	print_path("boardRoot", NATIVE_BOARD_ROOT)
	print_path("boardDir", NATIVE_BOARD_DIR)
	print_path("openocdCfg", NATIVE_OPENOCD_CFG)
	print_path("buildDir", NATIVE_BUILD_DIR)
	print_path("firmwareElf", NATIVE_FIRMWARE_ELF)
	print_path("firmwareHex", NATIVE_FIRMWARE_HEX)
	print_path("toolchain", native_toolchain_dir())
	print_path("toolchainGcc", native_toolchain_dir() / "bin" / "arm-none-eabi-gcc")
	print_path("commonToolchain", NATIVE_TOOLCHAIN_DIR)
	print_path("platformioToolchain", PIO_TOOLCHAIN_DIR)
	print_path("repoLocalOpenocd", PIO_OPENOCD)
	print_path("repoLocalOpenocdScripts", PIO_OPENOCD_SCRIPTS)
	for module in NATIVE_ZEPHYR_MODULES:
		print_path("module", module)


def brew_paths() -> None:
	print(f"projectRoot: {PROJECT_ROOT}")
	print(f"deviceDir: {POWER_DEBUG_DIR}")
	print(f"board: {NATIVE_BOARD}")
	print(f"buildVersion: {BREW_BUILD_VERSION}")
	print_path("nativeVenv", NATIVE_VENV_DIR)
	print_path("nativePython", native_python())
	print_path("nativePipCache", NATIVE_PIP_CACHE_DIR)
	print_path("nativeZephyrCache", NATIVE_ZEPHYR_CACHE_DIR)
	print_path("nativeCcache", NATIVE_CCACHE_DIR)
	print_path("zephyrBase", NATIVE_ZEPHYR_BASE)
	print_path("seeedPlatform", NATIVE_SEEED_PLATFORM)
	print_path("boardRoot", NATIVE_BOARD_ROOT)
	print_path("boardDir", NATIVE_BOARD_DIR)
	print_path("openocdCfg", NATIVE_OPENOCD_CFG)
	print_path("buildDir", BREW_BUILD_DIR)
	print_path("firmwareElf", BREW_FIRMWARE_ELF)
	print_path("firmwareHex", BREW_FIRMWARE_HEX)
	print(f"toolchainVariant: cross-compile")
	print(f"crossCompile: {brew_cross_compile_prefix()}")
	print_path("brewGcc", brew_tool_path("gcc"))
	print_path("brewLdBfd", brew_tool_path("ld.bfd"))
	print_path("brewLd", brew_tool_path("ld"))
	print_path("brewObjcopy", brew_tool_path("objcopy"))
	print_path("brewSize", brew_tool_path("size"))
	print_path("repoLocalOpenocd", PIO_OPENOCD)
	print_path("repoLocalOpenocdScripts", PIO_OPENOCD_SCRIPTS)
	for module in NATIVE_ZEPHYR_MODULES:
		print_path("module", module)


def main() -> None:
	parser = argparse.ArgumentParser(description="Build power-debug firmware")
	parser.add_argument(
		"command",
		choices=[
			"install",
			"check",
			"build",
			"flash",
			"paths",
			"clean",
			"native-submodules",
			"native-install",
			"native-check",
			"native-build",
			"native-flash",
			"native-flash-command",
			"native-paths",
			"native-clean",
			"brew-install",
			"brew-check",
			"brew-build",
			"brew-flash",
			"brew-flash-command",
			"brew-paths",
			"brew-clean",
		],
	)
	args = parser.parse_args()

	if args.command == "install":
		install()
	elif args.command in {"check", "build"}:
		pio_run()
	elif args.command == "flash":
		pio_run("upload")
	elif args.command == "paths":
		paths()
	elif args.command == "clean":
		clean()
	elif args.command == "native-submodules":
		native_submodules()
	elif args.command == "native-install":
		native_install()
	elif args.command in {"native-check", "native-build"}:
		native_build()
	elif args.command == "native-flash":
		native_flash()
	elif args.command == "native-flash-command":
		native_flash_command()
	elif args.command == "native-paths":
		native_paths()
	elif args.command == "native-clean":
		native_clean()
	elif args.command == "brew-install":
		native_install()
		ensure_brew_toolchain()
	elif args.command in {"brew-check", "brew-build"}:
		brew_build()
	elif args.command == "brew-flash":
		brew_flash()
	elif args.command == "brew-flash-command":
		brew_flash_command()
	elif args.command == "brew-paths":
		brew_paths()
	elif args.command == "brew-clean":
		brew_clean()
	else:
		parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
	main()
