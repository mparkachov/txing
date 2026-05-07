# Power Debug Agent Guide

## Scope
- Keep changes isolated under `devices/power-debug/` unless the user explicitly asks for a shared firmware/toolchain change.
- Do not read from, copy from, execute from, or depend on files outside `/Users/Maxim/Developer/txing`; external examples or toolchain files must be pasted by the user or explicitly vendored into this repository first.
- Exception: this subproject may resolve the user-installed Homebrew `arm-none-eabi-*` binaries from `CROSS_COMPILE`/`POWER_DEBUG_CROSS_COMPILE`, normally `/opt/homebrew/bin/arm-none-eabi-*` on Apple Silicon macOS. Its manual flash command uses `openocd` from `PATH`.
- The build uses only repo-local Zephyr and Seeed board submodules under `devices/common/mcu/`, repo-local generated state under `devices/power-debug/mcu/`, and the Homebrew Arm toolchain.
- This subproject is for XIAO nRF54L15 board-floor power measurements only.
- It must not include legacy external build stacks, BLE, S115, SoftDevice, nRF-BM, repo NCS wrappers, production radio stacks, manufacturing data, BME280, battery measurement, or production device contracts.

## Hardware Rules
- Agents may run build/setup commands such as `just power-debug::mcu::submodules`, `just power-debug::mcu::install`, `just power-debug::mcu::check`, `just power-debug::mcu::build`, `just power-debug::mcu::flash-command`, `just power-debug::mcu::paths`, and `just power-debug::mcu::clean`.
- Agents must not run `just power-debug::mcu::flash`, OpenOCD, pyOCD, RTT, serial monitors, or other hardware-attached commands.
- Flashing and hardware verification are manual user actions.
