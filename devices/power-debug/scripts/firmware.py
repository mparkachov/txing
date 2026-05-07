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
ENV_NAME = "seeed-xiao-nrf54l15"

VENV_DIR = POWER_DEBUG_DIR / ".venv"
PIO_CORE_DIR = POWER_DEBUG_DIR / ".platformio-core"
PIO_HOME_DIR = POWER_DEBUG_DIR / ".home"
PIO_BUILD_DIR = POWER_DEBUG_DIR / ".pio" / "build" / ENV_NAME
PIP_CACHE_DIR = POWER_DEBUG_DIR / ".pip-cache"

PLATFORMIO_INI = POWER_DEBUG_DIR / "platformio.ini"
FIRMWARE_ELF = PIO_BUILD_DIR / "firmware.elf"
FIRMWARE_HEX = PIO_BUILD_DIR / "firmware.hex"


def venv_python() -> Path:
	if os.name == "nt":
		return VENV_DIR / "Scripts" / "python.exe"
	return VENV_DIR / "bin" / "python"


def pio_executable() -> Path:
	if os.name == "nt":
		return VENV_DIR / "Scripts" / "pio.exe"
	return VENV_DIR / "bin" / "pio"


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


def run(args: list[str | Path], *, cwd: Path = POWER_DEBUG_DIR) -> None:
	command = [str(arg) for arg in args]
	print(
		"+ (" + str(cwd) + ") " + " ".join(shlex.quote(part) for part in command),
		flush=True,
	)
	subprocess.run(command, cwd=cwd, env=env(), text=True, check=True)


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


def ensure_installed() -> None:
	if not pio_executable().exists():
		raise SystemExit(
			"missing repo-local PlatformIO. Run: just power-debug::firmware-install"
		)


def pio_run(target: str | None = None) -> None:
	ensure_installed()
	args: list[str | Path] = [pio_executable(), "run", "--environment", ENV_NAME]
	if target:
		args.extend(["--target", target])
	run(args)


def clean() -> None:
	for path in (POWER_DEBUG_DIR / ".pio",):
		if path.exists():
			print(f"removing {path}", flush=True)
			shutil.rmtree(path)


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


def main() -> None:
	parser = argparse.ArgumentParser(description="Build Seeed PlatformIO power-debug firmware")
	parser.add_argument(
		"command",
		choices=["install", "check", "build", "flash", "paths", "clean"],
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
	else:
		parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
	main()
