---
id: TASK-12.1
title: Power MCU builds with stock Zephyr stable
status: To Do
assignee: []
created_date: '2026-05-23 19:24'
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
- [ ] #1 Power MCU install/check/build use stock Zephyr latest stable with the stock xiao_nrf54l15/nrf54l15/cpuapp board.
- [ ] #2 power::mcu flash recipes remain direct OpenOCD commands and NVE generation continues to use the existing shared redcon_nve.py script.
- [ ] #3 just power::mcu::install, paths, check, build, check-flash, and check-nve power-test all succeed.
- [ ] #4 No files or temporary state are created in the user's HOME during install, check, build, or command inspection.
- [ ] #5 Generated config uses the stock Zephyr Bluetooth controller path and does not select NCS SoftDevice Controller settings.
<!-- AC:END -->
