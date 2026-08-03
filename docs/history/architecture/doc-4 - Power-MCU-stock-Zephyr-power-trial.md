---
id: doc-4
title: Power MCU stock Zephyr power trial
type: specification
created_date: '2026-05-23 19:23'
updated_date: '2026-05-23 19:23'
---
# Power MCU Stock Zephyr Power Trial

## Goal
Evaluate whether the existing `power` MCU firmware can run on stock Zephyr latest stable with the stock Seeed Studio XIAO nRF54L15 board definition, then use measurements from a known-good board to guide any later power-reduction customizations.

## Decisions
- Scope is limited to `devices/power/mcu` and `devices/power/README.md`.
- `unit`, `weather`, shared NCS tooling, NCS submodules, and common REDCON C code stay unchanged.
- The stock board identifier remains `xiao_nrf54l15/nrf54l15/cpuapp`; no local Seeed board definition or board fork is introduced.
- `nrfutil` is not used.
- No new Python build or bootstrap code is introduced. Existing `devices/common/mcu/xiao_nrf54l15/scripts/redcon_nve.py` remains the NVE HEX generator.
- Stock Zephyr latest stable is resolved during `power::mcu::install`; the expected release at plan time is `v4.4.0`.
- Host toolchain installation on macOS is allowed through standard C tooling such as `arm-none-eabi-gcc`, `cmake`, `ninja`, `dtc`, and `openocd`.

## Public Command Contract
The power MCU command surface remains: `install`, `paths`, `check`, `build`, `check-flash`, `build-nve-hex`, `check-nve`, `flash`, `flash-nve`, and `clean`.

`flash` and `flash-nve` remain manual OpenOCD workflows. Agents may build artifacts and print commands, but must not program hardware.

## Validation Strategy
First prove unmodified stock Zephyr compilation and flash-command readiness. Then manually flash and measure baseline power on known-good hardware. Only after the baseline is recorded, apply targeted stock-Zephyr power customizations and re-measure.
