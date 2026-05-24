---
id: doc-8
title: 'Milestone: MCU shared stock Zephyr tooling and power flash'
type: guide
created_date: '2026-05-24 13:20'
updated_date: '2026-05-24 13:21'
---
# Milestone: MCU Shared Stock Zephyr Tooling And Power Flash

## Outcome
The repository has one shared stock Zephyr v4.4.0 MCU workspace under `devices/common/mcu/`, root `mcu` just recipes, and the `power` MCU builds and prints flash/NVE commands through that shared stack.

## Scope
- Add root `mcu` recipe routing from the repository justfile to `devices/common/mcu/justfile`.
- Move the TASK-12 stock-Zephyr install/build/path/flash/NVE logic into shared MCU tooling.
- Convert `power::mcu::build`, `check`, `paths`, and `clean` to use the shared stack.
- Keep power REDCON behavior, NVE identity, OpenOCD command shape, and stock Zephyr v4.4.0 board target unchanged.

## Non-goals
- No weather or unit migration in this milestone.
- No NCS cleanup except what is required to avoid power depending on its per-device stock-Zephyr workspace.
- No firmware or NVE flashing by agents.

## Dependencies
- Completed TASK-12 power stock Zephyr baseline.
- Existing shared REDCON source and NVE writer under `devices/common/mcu/xiao_nrf54l15`.

## Validation
- `just mcu::install` succeeds or confirms the shared stock Zephyr workspace is ready.
- `just power::mcu::build` succeeds using the shared stack.
- `just mcu::check-flash power` prints the expected OpenOCD firmware command.
- `just mcu::check-nve power-test` generates the shared NVE HEX and prints the expected OpenOCD NVE command.

## Exit Criteria
The user can manually run `just mcu::flash power` and `just mcu::nve <thing-name>` using already-built shared-stack artifacts.
