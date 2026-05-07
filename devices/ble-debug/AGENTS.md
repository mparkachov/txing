# BLE Debug Agent Guide

## Scope
- Keep changes isolated under `devices/ble-debug/` unless the user explicitly asks for a shared firmware/toolchain change.
- Do not read from, copy from, execute from, or depend on files outside `/Users/Maxim/Developer/txing`; external examples or toolchain files must be pasted by the user or explicitly vendored into this repository first.
- Exception: this subproject may resolve the user-installed Homebrew `arm-none-eabi-*` binaries from `CROSS_COMPILE`/`BLE_DEBUG_CROSS_COMPILE`, normally `/opt/homebrew/bin/arm-none-eabi-*` on Apple Silicon macOS. Its manual flash command uses `openocd` from `PATH`.
- The build uses only repo-local Zephyr and Seeed board submodules under `devices/common/mcu/`, repo-local generated state under `devices/ble-debug/mcu/`, and the Homebrew Arm toolchain.
- This subproject is for XIAO nRF54L15 BLE advertising idle power measurements only.
- V1 is advertising-only. It must not include legacy external build stacks, GATT services, connection handling, wake/sleep commands, telemetry, BME280, battery measurement, factory/NVE data, S115, SoftDevice, nRF-BM, PlatformIO, or production device contracts.

## Hardware Rules
- Agents may run build/setup commands such as `just ble-debug::mcu::submodules`, `just ble-debug::mcu::install`, `just ble-debug::mcu::check`, `just ble-debug::mcu::build`, `just ble-debug::mcu::flash-check`, `just ble-debug::mcu::paths`, and `just ble-debug::mcu::clean`.
- Agents must not run `just ble-debug::mcu::flash`, OpenOCD, pyOCD, RTT, serial monitors, BLE scanner commands, or other hardware-attached commands.
- Flashing and hardware verification are manual user actions.
