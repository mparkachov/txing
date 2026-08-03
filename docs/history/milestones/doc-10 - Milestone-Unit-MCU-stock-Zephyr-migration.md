---
id: doc-10
title: 'Milestone: Unit MCU stock Zephyr migration'
type: guide
created_date: '2026-05-24 13:20'
updated_date: '2026-05-24 13:21'
---
# Milestone: Unit MCU Stock Zephyr Migration

## Outcome
The `unit` MCU builds on the shared stock Zephyr v4.4.0 stack and is physically validated against the rig/web REDCON workflow.

## Scope
- Convert unit `install`, `check`, `build`, `paths`, and `clean` behavior to the shared stock Zephyr stack.
- Remove stock-incompatible NCS-only configuration.
- Preserve REDCON 1/2/3/4 behavior, D1 power behavior, NVE identity, battery reporting, BLE command/state payloads, and rig-facing Sparkplug/shadow semantics.
- Keep the existing unit BLE TX-power setting initially unless physical validation shows stock-Zephyr connection instability.

## Non-goals
- No weather behavior changes.
- No NCS cleanup beyond removing unit's active dependency on NCS tooling.
- No protocol, schema, Sparkplug, or NVE layout changes.
- No firmware or NVE flashing by agents.

## Dependencies
- Shared stock Zephyr tooling and power flash milestone.
- Weather migration is expected to complete first so shared migration issues are resolved before unit validation.
- Existing unit device contracts and rig shadow/Sparkplug contract.

## Validation
- `just unit::mcu::check` and `just unit::mcu::build` pass on stock Zephyr.
- `just mcu::check-flash unit` prints the expected OpenOCD firmware command.
- `just mcu::check-nve unit-test` generates shared NVE HEX and prints the expected OpenOCD NVE command.
- User manually flashes unit firmware and NVE, then validates REDCON `4 -> 3 -> 2 -> 1 -> 4` as hardware allows through the rig/web workflow.

## Exit Criteria
Unit is no longer dependent on the NCS workspace for active builds, and physical validation confirms expected REDCON and rig-facing behavior on stock Zephyr.
