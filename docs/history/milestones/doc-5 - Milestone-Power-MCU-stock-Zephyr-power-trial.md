---
id: doc-5
title: 'Milestone: Power MCU stock Zephyr power trial'
type: guide
created_date: '2026-05-23 19:23'
updated_date: '2026-05-23 19:24'
---
# Milestone: Power MCU Stock Zephyr Power Trial

## Outcome
The power MCU can be evaluated on stock Zephyr latest stable in three reviewable stages: stock compilation and flash readiness, manual baseline measurement, and measured power-reduction customizations.

## Scope
- Only `devices/power/mcu` and `devices/power/README.md` are in scope.
- The shared REDCON implementation remains single-source in `devices/common/mcu/xiao_nrf54l15/src/redcon.c`.
- `power::mcu` keeps the same public command surface, NVE format, BLE identity behavior, REDCON protocol, and manual OpenOCD flashing behavior.

## Non-goals
- No changes to `unit`, `weather`, shared NCS workspace tooling, NCS submodules, or common MCU docs.
- No local Seeed board definition and no board fork.
- No `nrfutil` workflow.
- No new Python build or bootstrap code.
- No automatic firmware or NVE flashing by agents.

## Dependencies
- Existing REDCON C implementation and Kconfig under `devices/common/mcu/xiao_nrf54l15`.
- Existing power MCU app sources under `devices/power/mcu`.
- Existing shared NVE writer `devices/common/mcu/xiao_nrf54l15/scripts/redcon_nve.py`.
- Stock Zephyr latest stable and the stock `xiao_nrf54l15/nrf54l15/cpuapp` board.

## Validation
- Every implementation task finishes with successful `just power::mcu::build` or stronger `check/build/check-flash/check-nve` validation.
- Flashing and current measurement are manual user actions.
- Task notes record manual measurement results before power customizations are attempted.

## Exit Criteria
- Task 1 proves stock Zephyr compilation and flash-command readiness.
- Task 2 records known-good-board baseline power measurements using the stock Zephyr firmware.
- Task 3 records before/after measurements for any stock-Zephyr power-reduction customizations.
