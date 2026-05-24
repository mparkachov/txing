---
id: doc-9
title: 'Milestone: Weather MCU stock Zephyr migration'
type: guide
created_date: '2026-05-24 13:20'
updated_date: '2026-05-24 13:21'
---
# Milestone: Weather MCU Stock Zephyr Migration

## Outcome
The `weather` MCU builds on the shared stock Zephyr v4.4.0 stack and is physically validated after manual firmware and NVE flashing.

## Scope
- Convert weather `install`, `check`, `build`, `paths`, and `clean` behavior to the shared stock Zephyr stack.
- Remove stock-incompatible NCS-only configuration.
- Preserve REDCON 4 behavior, BME280 measurement payload format, battery reporting, NVE identity, and D1 BME280 power control.
- Keep the existing weather BLE TX-power setting initially unless physical validation shows stock-Zephyr connection instability.

## Non-goals
- No unit migration.
- No NCS cleanup beyond removing weather's active dependency on NCS tooling.
- No protocol, schema, or NVE layout changes.
- No firmware or NVE flashing by agents.

## Dependencies
- Shared stock Zephyr tooling and power flash milestone.
- Existing weather REDCON/BME280 implementation and devicetree overlay.

## Validation
- `just weather::mcu::check` and `just weather::mcu::build` pass on stock Zephyr.
- `just mcu::check-flash weather` prints the expected OpenOCD firmware command.
- `just mcu::check-nve weather-test` generates shared NVE HEX and prints the expected OpenOCD NVE command.
- User manually flashes weather firmware and NVE, then validates BLE identity, REDCON service, weather measurement, and battery measurement behavior.

## Exit Criteria
Weather is no longer dependent on the NCS workspace for active builds, and physical validation confirms expected weather MCU functionality on stock Zephyr.
