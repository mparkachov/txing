# mcu subproject guide

## Scope
- This directory contains the NCS/Zephyr firmware for the unit MCU.
- The target board is `xiao_nrf54l15/nrf54l15/cpuapp`.

## Notes
- Run firmware build/test commands from `mcu/` through the `just unit::mcu::*` recipes.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Do not flash firmware or NVE records automatically; prepare artifacts and commands only.
- Use `../aws/ble-shadow.schema.json` and `../aws/power-shadow.schema.json` as the BLE/power shadow contract references.
- Treat `rig` as owner of the `ble` and `power` named shadow contracts.

## Shared workflow
- Follow the repository-level Beads workflow in `../AGENTS.md`.
- If an `mcu/`-specific task is created under a shared epic, mention `mcu/` in the Beads title or description so ownership is obvious.
