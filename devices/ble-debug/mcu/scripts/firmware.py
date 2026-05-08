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
REQUIRED_PROFILE_FIELDS = (
	"description",
	"interval",
	"txPowerDbm",
	"connectable",
	"scannable",
	"includeUuid",
	"gatt",
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
		raise SystemExit(f"missing BLE debug MCU config: {CONFIG_PATH}")

	config: dict[str, object] = {"defaults": {}, "profiles": {}}
	section: str | None = None
	current_profile: str | None = None
	with CONFIG_PATH.open("r", encoding="utf-8") as handle:
		for line_number, raw_line in enumerate(handle, start=1):
			line = raw_line.split("#", 1)[0].rstrip()
			if not line.strip():
				continue
			if line.startswith("\t"):
				raise SystemExit(f"{CONFIG_PATH}:{line_number}: use spaces, not tabs")

			indent = len(line) - len(line.lstrip(" "))
			text = line.strip()
			if indent == 0:
				current_profile = None
				if text in {"defaults:", "profiles:"}:
					section = text[:-1]
					continue
				key, value = split_yaml_key_value(text, line_number)
				config[key] = value
				section = None
			elif indent == 2 and section == "defaults":
				key, value = split_yaml_key_value(text, line_number)
				defaults = config["defaults"]
				assert isinstance(defaults, dict)
				defaults[key] = value
			elif indent == 2 and section == "profiles":
				if not text.endswith(":"):
					raise SystemExit(f"{CONFIG_PATH}:{line_number}: expected profile:")
				current_profile = text[:-1].strip()
				if not current_profile:
					raise SystemExit(f"{CONFIG_PATH}:{line_number}: empty profile name")
				profiles = config["profiles"]
				assert isinstance(profiles, dict)
				profiles[current_profile] = {}
			elif indent == 4 and section == "profiles" and current_profile is not None:
				key, value = split_yaml_key_value(text, line_number)
				profiles = config["profiles"]
				assert isinstance(profiles, dict)
				profile_config = profiles[current_profile]
				assert isinstance(profile_config, dict)
				profile_config[key] = value
			else:
				raise SystemExit(f"{CONFIG_PATH}:{line_number}: unsupported indentation")
	return config


def load_mcu_config() -> dict[str, object]:
	global _CONFIG_CACHE

	if _CONFIG_CACHE is not None:
		return _CONFIG_CACHE

	raw_config = load_raw_mcu_config()
	default_profile = str(raw_config.get("defaultProfile", "")).strip()
	defaults = raw_config.get("defaults", {})
	profiles = raw_config.get("profiles", {})
	if not default_profile:
		raise SystemExit(f"{CONFIG_PATH}: missing defaultProfile")
	if not isinstance(defaults, dict) or not isinstance(profiles, dict) or not profiles:
		raise SystemExit(f"{CONFIG_PATH}: expected defaults and profiles mappings")

	merged_profiles: dict[str, dict[str, object]] = {}
	for name, profile_config in profiles.items():
		if not isinstance(name, str) or not isinstance(profile_config, dict):
			raise SystemExit(f"{CONFIG_PATH}: invalid profile entry {name!r}")
		merged = {**defaults, **profile_config}
		missing = [field for field in REQUIRED_PROFILE_FIELDS if field not in merged]
		if missing:
			raise SystemExit(
				f"{CONFIG_PATH}: profile {name!r} missing fields: {', '.join(missing)}"
			)
		merged_profiles[name] = merged
	if default_profile not in merged_profiles:
		raise SystemExit(f"{CONFIG_PATH}: defaultProfile {default_profile!r} is not defined")

	_CONFIG_CACHE = {
		"defaultProfile": default_profile,
		"profiles": merged_profiles,
	}
	return _CONFIG_CACHE


def default_profile() -> str:
	return str(load_mcu_config()["defaultProfile"])


def profile_configs() -> dict[str, dict[str, object]]:
	profiles = load_mcu_config()["profiles"]
	assert isinstance(profiles, dict)
	return profiles


def profile_config(profile: str) -> dict[str, object]:
	profiles = profile_configs()
	return profiles[profile]


def cmake_bool(value: object) -> str:
	if isinstance(value, bool):
		return "1" if value else "0"
	text = str(value).strip().lower()
	if text in {"1", "true", "yes", "on"}:
		return "1"
	if text in {"0", "false", "no", "off"}:
		return "0"
	raise SystemExit(f"expected boolean profile value, got {value!r}")


def normalize_profile(profile: str | None) -> str:
	selected = profile or os.environ.get("BLE_DEBUG_PROFILE") or default_profile()
	if selected not in profile_configs():
		options = ", ".join(profile_configs())
		raise SystemExit(f"unknown ble-debug profile '{selected}'. Options: {options}")
	return selected


def build_dir(profile: str) -> Path:
	return MCU_DIR / "build" / f"zephyr-xiao_nrf54l15_cpuapp-brew-{profile}"


def firmware_elf(profile: str) -> Path:
	return build_dir(profile) / "zephyr" / "zephyr.elf"


def firmware_hex(profile: str) -> Path:
	return build_dir(profile) / "zephyr" / "zephyr.hex"


def python_executable() -> Path:
	if os.name == "nt":
		return VENV_DIR / "Scripts" / "python.exe"
	return VENV_DIR / "bin" / "python"


def cross_compile_prefix() -> str:
	configured = os.environ.get("BLE_DEBUG_CROSS_COMPILE") or os.environ.get("CROSS_COMPILE")
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
			"missing OpenOCD for ble-debug flash.\n"
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
	local["BLE_DEBUG_BOARD_ROOT"] = str(BOARD_ROOT)
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
			"missing ble-debug Zephyr submodules. Run:\n"
			"  just ble-debug::mcu::submodules\n"
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
			"missing ble-debug Python environment. Run: "
			"just ble-debug::mcu::install"
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
			"Or set BLE_DEBUG_CROSS_COMPILE to a full prefix such as "
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
		print(f"creating ble-debug Zephyr venv: {VENV_DIR}", flush=True)
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


def configure(profile: str) -> None:
	ensure_ready()
	cfg = profile_config(profile)
	selected_build_dir = build_dir(profile)
	selected_build_dir.mkdir(parents=True, exist_ok=True)
	module_arg = ";".join(str(path) for path in ZEPHYR_MODULES)
	conf_files = [MCU_DIR / "zephyr" / "prj.conf"]
	if cmake_bool(cfg["gatt"]) == "1":
		conf_files.append(MCU_DIR / "zephyr" / "prj-gatt.conf")
	conf_file_arg = ";".join(str(path) for path in conf_files)
	run(
		[
			"cmake",
			"-S",
			MCU_DIR / "zephyr",
			"-B",
			selected_build_dir,
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
			f"-DBLE_DEBUG_ADV_INTERVAL={cfg['interval']}",
			f"-DBLE_DEBUG_ADV_TX_POWER_DBM={cfg['txPowerDbm']}",
			f"-DBLE_DEBUG_ADV_CONNECTABLE={cmake_bool(cfg['connectable'])}",
			f"-DBLE_DEBUG_ADV_SCANNABLE={cmake_bool(cfg['scannable'])}",
			f"-DBLE_DEBUG_ADV_INCLUDE_UUID={cmake_bool(cfg['includeUuid'])}",
			f"-DBLE_DEBUG_GATT={cmake_bool(cfg['gatt'])}",
			"-DZEPHYR_TOOLCHAIN_VARIANT=cross-compile",
			f"-DCROSS_COMPILE={cross_compile_prefix()}",
			"-DUSE_CCACHE=0",
			"-DCCACHE_PROGRAM=CCACHE_PROGRAM-NOTFOUND",
			"-DCMAKE_C_COMPILER_LAUNCHER=",
			"-DCMAKE_CXX_COMPILER_LAUNCHER=",
		],
	)


def build(profile: str) -> None:
	configure(profile)
	run(["cmake", "--build", build_dir(profile)])


def flash_openocd_command(profile: str) -> list[Path | str]:
	selected_hex = firmware_hex(profile)
	if not selected_hex.exists():
		raise SystemExit(f"missing firmware hex. Run: just ble-debug::mcu::check {profile}")
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
		f"nrf54l-load {selected_hex}",
		"-c",
		f"verify_image {selected_hex}",
		"-c",
		"reset run",
		"-c",
		"shutdown",
	]


def flash(profile: str) -> None:
	run(flash_openocd_command(profile))


def flash_check(profile: str) -> None:
	ensure_ready()
	command = [str(part) for part in flash_openocd_command(profile)]
	print(" ".join(shlex.quote(part) for part in command))


def clean() -> None:
	build_root = MCU_DIR / "build"
	for profile in profile_configs():
		selected_build_dir = build_dir(profile)
		if selected_build_dir.exists():
			print(f"removing {selected_build_dir}", flush=True)
			shutil.rmtree(selected_build_dir)

	legacy_build_dir = build_root / "zephyr-xiao_nrf54l15_cpuapp-brew"
	if legacy_build_dir.exists():
		print(f"removing {legacy_build_dir}", flush=True)
		shutil.rmtree(legacy_build_dir)


def print_path(label: str, path: Path) -> None:
	print(f"{label}: {path} exists={int(path.exists())}")


def paths(profile: str) -> None:
	cfg = profile_config(profile)
	print(f"projectRoot: {PROJECT_ROOT}")
	print(f"deviceDir: {DEVICE_DIR}")
	print(f"mcuDir: {MCU_DIR}")
	print(f"board: {BOARD}")
	print(f"buildVersion: {BUILD_VERSION}")
	print(f"config: {CONFIG_PATH}")
	print(f"defaultProfile: {default_profile()}")
	print(f"profile: {profile}")
	print(f"profileDescription: {cfg['description']}")
	print(f"advInterval: {cfg['interval']}")
	print(f"advTxPowerDbm: {cfg['txPowerDbm']}")
	print(f"advConnectable: {cmake_bool(cfg['connectable'])}")
	print(f"advScannable: {cmake_bool(cfg['scannable'])}")
	print(f"advIncludeUuid: {cmake_bool(cfg['includeUuid'])}")
	print(f"gatt: {cmake_bool(cfg['gatt'])}")
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
	print_path("buildDir", build_dir(profile))
	print_path("firmwareElf", firmware_elf(profile))
	print_path("firmwareHex", firmware_hex(profile))
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
	parser = argparse.ArgumentParser(description="Build ble-debug firmware")
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
	parser.add_argument(
		"profile",
		nargs="?",
		help=f"advertising profile; default is {default_profile()}",
	)
	args = parser.parse_args()
	profile = normalize_profile(args.profile)

	if args.command == "submodules":
		submodules()
	elif args.command == "install":
		install()
	elif args.command in {"check", "build"}:
		build(profile)
	elif args.command == "flash":
		flash(profile)
	elif args.command == "flash-check":
		flash_check(profile)
	elif args.command == "paths":
		paths(profile)
	elif args.command == "clean":
		clean()


if __name__ == "__main__":
	main()
