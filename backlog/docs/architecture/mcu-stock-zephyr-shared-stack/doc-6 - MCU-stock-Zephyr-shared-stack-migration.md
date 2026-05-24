---
id: doc-6
title: MCU stock Zephyr shared stack migration
type: specification
created_date: '2026-05-24 13:20'
updated_date: '2026-05-24 18:48'
---
# MCU Stock Zephyr Shared Stack Migration

## Goal
Move the active XIAO nRF54L15 MCU firmware targets (`power`, `weather`, and `unit`) from the current mixed NCS/stock-Zephyr setup to one shared stock Zephyr v4.4.0 stack under `devices/common/mcu/`.

TASK-12 is the baseline: the power MCU has already validated stock Zephyr v4.4.0 with the stock `xiao_nrf54l15/nrf54l15/cpuapp` board, the shared REDCON implementation, the existing NVE format, and direct OpenOCD flash commands.

## Current State
- `power`, `weather`, and `unit` build on stock Zephyr v4.4.0 from the shared workspace under `devices/common/mcu/zephyr`.
- `devices/common/mcu/xiao_nrf54l15` owns shared REDCON source, headers, Kconfig, board defaults, and the NVE writer.
- The obsolete NCS helper, generated NCS workspace, and `modules/nrfconnect/sdk-nrf` submodule are retired by the MCU NCS cleanup milestone.

## Intended Command Contract
Shared setup and hardware command surfaces move to root `mcu` recipes:

```sh
just mcu::install
just mcu::check
just mcu::flash power
just mcu::flash weather
just mcu::flash unit
just mcu::nve <thing-name>
```

Device-owned build surfaces remain local:

```sh
just power::mcu::build
just weather::mcu::build
just unit::mcu::build
```

`mcu::flash <device-type>` flashes an already-built firmware HEX for that device and must not implicitly build firmware. NVE generation remains shared because the TXR1 record layout, address `0x000f0000`, and OpenOCD command are common across active MCU targets.

## Phased Migration
1. Build the shared stock-Zephyr toolchain/workspace in `devices/common/mcu/`, add root `mcu` recipes, and migrate `power` to prove the shared stack still works for the TASK-12 baseline.
2. Migrate `weather`, preserving REDCON 4, BME280 measurement payloads, NVE identity, and D1 sensor-power behavior.
3. Migrate `unit`, preserving REDCON 1/2/3/4, D1 power behavior, battery reporting, NVE identity, and rig-facing Sparkplug/shadow semantics.
4. Remove obsolete NCS build paths, wrappers, docs, and the `modules/nrfconnect/sdk-nrf` submodule after all active MCU targets build and validate on stock Zephyr.

## Non-goals
- No Zephyr version upgrade beyond v4.4.0.
- No BLE protocol, UUID, payload, NVE layout, Thing Shadow schema, Sparkplug contract, or rig ownership changes.
- No automatic firmware or NVE flashing by agents.
- No `nrfutil` workflow.
- No local Seeed board fork unless a later explicit milestone proves stock board support is insufficient.

## Validation Strategy
Each milestone must end with local build validation and `just mcu::check` preflight validation. Physical firmware and NVE flashing remain manual user actions. Manual hardware validation records BLE identity, REDCON service behavior, battery reporting, and device-specific behavior before the next milestone starts.
