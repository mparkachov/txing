---
id: TASK-12.2
title: Power MCU stock Zephyr baseline flash and measurement
status: Done
assignee:
  - Codex
created_date: '2026-05-23 19:24'
updated_date: '2026-05-23 21:52'
labels: []
milestone: Power MCU stock Zephyr power trial
dependencies:
  - TASK-12.1
references:
  - devices/power/mcu
  - devices/power/README.md
documentation:
  - >-
    backlog/docs/architecture/power-mcu-stock-zephyr-power-trial/doc-4 -
    Power-MCU-stock-Zephyr-power-trial.md
  - >-
    backlog/docs/milestones/power-mcu-stock-zephyr-power-trial/doc-5 -
    Milestone-Power-MCU-stock-Zephyr-power-trial.md
parent_task_id: TASK-12
ordinal: 19000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 just power::mcu::build succeeds immediately before any manual flashing.
- [x] #2 The user manually runs power::mcu flash and flash-nve on a known-good board using the Task 1 firmware.
- [x] #3 Manual BLE validation confirms NVE device name, REDCON service, REDCON 3 wake behavior, and REDCON 4 sleep behavior match the existing power firmware contract.
- [x] #4 Baseline REDCON 4 advertising-idle and connected-idle current measurements are recorded in task notes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify the current branch builds the stock Zephyr power MCU firmware immediately before manual flash/measurement evidence is recorded.
2. Confirm the generated stock configuration is the split LL path at 0 dBm and print flash/NVE commands without programming hardware.
3. Record the user's manual flash, BLE validation, and REDCON 4 current measurements from the known-good board.
4. Check only acceptance criteria with direct evidence and mark the task Done once all criteria are satisfied.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-05-23 baseline evidence:
- Current branch `feature/power-mcu-stock-zephyr` built stock Zephyr v4.4.0 with `just power::mcu::build`; build output reported FLASH 112200 B and RAM 20107 B.
- Generated stock config was verified from `devices/power/mcu/build/zephyr-xiao_nrf54l15_cpuapp/zephyr/.config`: `CONFIG_BT_LL_SW_SPLIT=y`, no SoftDevice controller setting, `CONFIG_BT_CTLR_TX_PWR_0=y`, `CONFIG_BT_CTLR_TX_PWR_DBM=0`, and advertising TX power `CONFIG_REDCON_BLE_ADV_TX_POWER_DBM=4`.
- `just power::mcu::check-flash` printed the direct OpenOCD firmware flash command for `build/zephyr-xiao_nrf54l15_cpuapp/zephyr/zephyr.hex`; no agent flashing was performed.
- `just power::mcu::check-nve power-mm8ou5` generated `build/zephyr-xiao_nrf54l15_cpuapp/redcon-factory-nve.hex` at address `0x000f0000` with deviceName `power-mm8ou5` and printed the direct OpenOCD NVE flash command; no agent flashing was performed.
- User manually flashed the known-good board and NVE during the stock-Zephyr baseline session. BLE validation showed device `E4:7C:BC:45:9B:A2`, name/alias `power-mm8ou5`, REDCON service UUID `f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100`, and GATT characteristics `f6b4b001`, `f6b4b002`, and `f6b4b003`.
- Manual REDCON validation: after controller TX power was set to 0 dBm, the device connected from the rig/web UI consistently and user reported repeated web UI `4 - 3 - 4` transitions as stable, covering REDCON 3 wake and REDCON 4 sleep behavior for this baseline.
- Manual current measurements on the same known-good board: REDCON 4 advertising/disconnected idle after rig removal and power cycle measured about 0.06 mA; stock Zephyr connected idle measured about 0.10 mA. A temporary NCS/SoftDevice comparison build using the same shared REDCON code measured about 0.08 mA connected idle, confirming the stock baseline delta belongs to the controller/clock path rather than REDCON app logic, NVE, rig behavior, or board placement.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed the stock Zephyr baseline measurement task for the known-good power MCU board. Verified `just power::mcu::build`, stock split-LL generated config at 0 dBm, and direct OpenOCD command generation for firmware and NVE. Recorded user manual BLE validation for NVE name `power-mm8ou5`, REDCON service/characteristics, stable web UI REDCON 4-3-4 transitions, and baseline current measurements: about 0.06 mA advertising/disconnected idle and about 0.10 mA connected idle. A temporary NCS/SoftDevice comparison measured about 0.08 mA connected idle, so the stock baseline delta is attributed to the stock Zephyr controller/clock path.
<!-- SECTION:FINAL_SUMMARY:END -->
