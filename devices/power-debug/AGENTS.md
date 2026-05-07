# Power Debug Agent Guide

## Scope
- Keep changes isolated under `devices/power-debug/` unless the user explicitly asks for a shared firmware/toolchain change.
- Do not read from, copy from, execute from, or depend on files outside `/Users/Maxim/Developer/txing`; external examples or toolchain files must be pasted by the user or explicitly vendored into this repository first.
- All PlatformIO state for the reference build must live under `devices/power-debug/`.
- The native Zephyr build must use only repo-local submodules under `devices/common/mcu/`, repo-local generated state under `devices/power-debug/`, plus a repo-local GNU Arm Embedded toolchain path. The repo-local PlatformIO GCC/OpenOCD packages are allowed as fallback host tools. Do not use global Zephyr, global NCS, global PlatformIO packages, or files outside this repository.
- This subproject is for XIAO nRF54L15 board-floor power measurements only.
- The PlatformIO reference build uses the Seeed-provided PlatformIO Zephyr stack with `board = seeed-xiao-nrf54l15`.
- The native build uses Zephyr `4.2.1`, Seeed platform commit `957214493cecaf4f77a3d7d2cc7f75cec6b76c83`, `xiao_nrf54l15/nrf54l15/cpuapp`, `gnuarmemb`, and GCC `8.2.1`.
- It must not include BLE, S115, SoftDevice, nRF-BM, repo NCS wrappers, production radio stacks, manufacturing data, BME280, battery measurement, or production device contracts.

## Hardware Rules
- Agents may run build/setup commands such as `just power-debug::firmware-install`, `just power-debug::firmware-check`, `just power-debug::firmware-build`, `just power-debug::firmware-paths`, `just power-debug::firmware-clean`, `just power-debug::firmware-native-submodules`, `just power-debug::firmware-native-install`, `just power-debug::firmware-native-check`, `just power-debug::firmware-native-build`, `just power-debug::firmware-native-flash-command`, `just power-debug::firmware-native-paths`, and `just power-debug::firmware-native-clean`.
- Agents must not run `just power-debug::firmware-flash`, `just power-debug::firmware-native-flash`, `pio run -t upload`, OpenOCD, pyOCD, RTT, serial monitors, or other hardware-attached commands.
- Flashing and hardware verification are manual user actions.
