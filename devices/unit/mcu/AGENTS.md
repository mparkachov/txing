# mcu subproject guide

## Scope
- This directory contains the stock Zephyr firmware for the unit MCU.
- The target board is `xiao_nrf54l15/nrf54l15/cpuapp`.

## Notes
- Run shared setup/preflight from the repo root with `just mcu::install` and
  `just mcu::check`; keep device firmware builds under `just unit::mcu::build`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Do not flash firmware or NVE records automatically; prepare artifacts and commands only.
- Read `../../../docs/components/mcu.md` before changing the shared XIAO
  nRF54L15 firmware stack.
- Use `../aws/ble-shadow.schema.json` and `../aws/power-shadow.schema.json` as the BLE/power shadow contract references.
- Treat `rig` as owner of the `ble` and `power` named shadow contracts.
- Do not copy `redcon.c`, fork the REDCON UUID/payload handling, or add a
  per-device Zephyr install/build path for a XIAO nRF54L15 target.

## Shared workflow
- Follow the repository-level Backlog.md workflow in `../../../AGENTS.md`.
- If an `mcu/`-specific task is created under a shared milestone, mention
  `devices/unit/mcu/` in the Backlog task title or description so ownership is
  obvious.
