---
id: TASK-12.2
title: Power MCU stock Zephyr baseline flash and measurement
status: To Do
assignee: []
created_date: '2026-05-23 19:24'
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
- [ ] #1 just power::mcu::build succeeds immediately before any manual flashing.
- [ ] #2 The user manually runs power::mcu flash and flash-nve on a known-good board using the Task 1 firmware.
- [ ] #3 Manual BLE validation confirms NVE device name, REDCON service, REDCON 3 wake behavior, and REDCON 4 sleep behavior match the existing power firmware contract.
- [ ] #4 Baseline REDCON 4 advertising-idle and connected-idle current measurements are recorded in task notes.
<!-- AC:END -->
