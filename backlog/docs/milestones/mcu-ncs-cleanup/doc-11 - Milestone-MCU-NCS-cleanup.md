---
id: doc-11
title: 'Milestone: MCU NCS cleanup'
type: guide
created_date: '2026-05-24 13:20'
updated_date: '2026-05-24 13:21'
---
# Milestone: MCU NCS Cleanup

## Outcome
After all active MCU targets build and validate on the shared stock Zephyr stack, obsolete NCS build paths, wrappers, docs, and the Nordic `sdk-nrf` git submodule are removed.

## Scope
- Remove active NCS helper scripts and per-device wrapper scripts that are no longer used.
- Remove the `modules/nrfconnect/sdk-nrf` submodule and related `.gitmodules` entry.
- Remove or retire generated NCS workspace documentation under `devices/common/mcu/ncs`.
- Remove obsolete generated build/cache/workspace folders from device-specific MCU directories after their shared stock Zephyr builds are validated.
- Update MCU component docs, device MCU READMEs, and agent guidance to describe stock Zephyr as the active MCU stack.
- Confirm no active source or docs still tell users to use NCS for active MCU builds.

## Non-goals
- No firmware behavior changes.
- No Zephyr version upgrade.
- No deletion of unrelated generated build artifacts outside the MCU migration surface.
- No hardware flashing by agents.

## Dependencies
- Shared stock Zephyr tooling and power flash milestone.
- Weather MCU stock Zephyr migration.
- Unit MCU stock Zephyr migration.

## Validation
- `just power::mcu::build`, `just weather::mcu::build`, and `just unit::mcu::build` all pass on the shared stock Zephyr stack.
- `just mcu::check-flash power`, `weather`, and `unit` all print valid firmware commands.
- `just mcu::check-nve power-test`, `weather-test`, and `unit-test` all print valid NVE commands.
- Source/doc searches show no active NCS command path remains for active MCU builds.
- Device-specific MCU directories contain only source/config/tooling that remains part of the active stock Zephyr flow.

## Exit Criteria
The active MCU build and flash documentation describes only the shared stock Zephyr stack, and the repository no longer tracks the NCS submodule for active MCU firmware.
