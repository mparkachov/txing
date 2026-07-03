---
id: TASK-12.1
title: Power MCU builds with stock Zephyr stable
status: Done
assignee:
  - Codex
created_date: '2026-05-23 19:24'
updated_date: '2026-05-23 23:58'
labels: []
milestone: Power MCU stock Zephyr power trial
dependencies: []
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
modified_files:
  - devices/power/mcu/justfile
  - devices/power/mcu/zephyr/prj.conf
  - devices/power/mcu/.gitignore
  - devices/power/README.md
parent_task_id: TASK-12
ordinal: 18000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Power MCU install/check/build use stock Zephyr latest stable with the stock xiao_nrf54l15/nrf54l15/cpuapp board.
- [x] #2 power::mcu flash recipes remain direct OpenOCD commands and NVE generation continues to use the existing shared redcon_nve.py script.
- [x] #3 just power::mcu::install, paths, check, build, check-flash, and check-nve power-test all succeed.
- [x] #4 No files or temporary state are created in the user's HOME during install, check, build, or command inspection.
- [x] #5 Generated config uses the stock Zephyr Bluetooth controller path and does not select NCS SoftDevice Controller settings.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Compare current power MCU Zephyr setup against the stock Zephyr latest-stable requirement.
2. Update install/path/build configuration to use stock Zephyr and xiao_nrf54l15/nrf54l15/cpuapp while preserving OpenOCD flash and shared redcon_nve.py NVE generation.
3. Update scoped docs/ignore files only as needed.
4. Verify install/check/build/check-flash/check-nve behavior and generated config constraints.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented power MCU stock Zephyr build/install flow pinned to stock Zephyr v4.4.0 using the stock xiao_nrf54l15/nrf54l15/cpuapp board. Preserved direct OpenOCD flash/check-flash recipes and shared redcon_nve.py NVE generation. Verified install, paths, check, build, check-flash, and check-nve power-test; generated config selects the stock Zephyr split LL controller path and contains no NCS SoftDevice/SDC settings. Recipes export HOME and caches into directories under devices/power/mcu plus the repo-local tmp directory.

Manual measurement follow-up on 2026-05-23: with the same board, rig setup, shared REDCON code, and NVE identity, the stock Zephyr v4.4.0 split-LL power firmware required `CONFIG_BT_CTLR_TX_PWR_0=y` for stable rig connection and measured about 0.10 mA while connected idle. A temporary NCS/SoftDevice power experiment using the same shared REDCON code and `CONFIG_BT_CTLR_TX_PWR_MINUS_20=y` measured about 0.08 mA while connected idle, matching the unit firmware. Rebuilding the current stock-Zephyr branch restored the expected stock config (`CONFIG_BT_LL_SW_SPLIT=y`, `CONFIG_BT_CTLR_TX_PWR_DBM=0`) and reproduced about 0.10 mA connected idle. Conclusion: the connected-idle delta is attributable to the stock Zephyr controller/clock path rather than the REDCON application logic, NVE, hardware placement, or rig behavior.
<!-- SECTION:FINAL_SUMMARY:END -->
