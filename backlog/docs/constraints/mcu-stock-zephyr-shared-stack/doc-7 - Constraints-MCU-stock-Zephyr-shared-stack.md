---
id: doc-7
title: 'Constraints: MCU stock Zephyr shared stack'
type: guide
created_date: '2026-05-24 13:20'
updated_date: '2026-05-24 13:20'
---
# Constraints: MCU Stock Zephyr Shared Stack

## Stack Ownership
- Active MCU targets are `devices/power/mcu`, `devices/weather/mcu`, and `devices/unit/mcu`.
- Shared stock Zephyr workspace, Python/west environment, caches, and helper recipes belong under `devices/common/mcu/`.
- Shared REDCON source and NVE logic remain in `devices/common/mcu/xiao_nrf54l15`.
- Device-specific behavior remains in local `src/main.c`, `zephyr/prj.conf`, Kconfig, and devicetree overlays.

## Command Rules
- Builds stay device-owned through `just <device>::mcu::build` and `check`.
- Shared setup and hardware programming commands use root `mcu` recipes.
- `mcu::flash <device-type>` must use an existing built firmware HEX and must not build implicitly.
- NVE commands are shared because the TXR1 layout and address `0x000f0000` are common.
- Just recipe arguments remain positional.

## Safety Rules
- Agents must not run firmware or NVE flashing commands.
- Agents may run build/check/path commands and `check-flash` / `check-nve` recipes that print commands without programming hardware.
- Host tools remain manual prerequisites: `git`, `python3`, `cmake`, `ninja`, `dtc`, `arm-none-eabi-gcc`, and `openocd`.
- Repository shell and just code must stay POSIX `sh` compatible.

## Compatibility Rules
- Stock Zephyr stays pinned to v4.4.0 for this migration.
- REDCON protocol, UUIDs, payloads, NVE layout, BLE identity behavior, Thing Shadow schemas, and Sparkplug semantics are unchanged.
- Existing unit/weather BLE TX-power settings should be preserved initially; only change them if physical stock-Zephyr validation shows connection instability, and record the reason.
