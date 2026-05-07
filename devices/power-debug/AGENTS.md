# Power Debug Agent Guide

## Scope
- Keep changes isolated under `devices/power-debug/` unless the user explicitly asks for a shared firmware/toolchain change.
- Do not read from, copy from, execute from, or depend on files outside `/Users/Maxim/Developer/txing`; external examples or toolchain files must be pasted by the user or explicitly vendored into this repository first.
- All PlatformIO, Seeed platform, Zephyr framework, board, package, cache, and toolchain state for this subproject must live under `devices/power-debug/`.
- This subproject is for XIAO nRF54L15 board-floor power measurements only.
- It uses the Seeed-provided PlatformIO Zephyr stack with `board = seeed-xiao-nrf54l15`.
- It must not include BLE, S115, SoftDevice, nRF-BM, repo NCS wrappers, production radio stacks, manufacturing data, BME280, battery measurement, or production device contracts.

## Hardware Rules
- Agents may run build/setup commands such as `just power-debug::firmware-install`, `just power-debug::firmware-check`, `just power-debug::firmware-build`, `just power-debug::firmware-paths`, and `just power-debug::firmware-clean`.
- Agents must not run `just power-debug::firmware-flash`, `pio run -t upload`, OpenOCD, pyOCD, RTT, serial monitors, or other hardware-attached commands.
- Flashing and hardware verification are manual user actions.
