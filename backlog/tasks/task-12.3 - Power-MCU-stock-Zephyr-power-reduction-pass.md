---
id: TASK-12.3
title: Power MCU stock Zephyr power reduction pass
status: To Do
assignee: []
created_date: '2026-05-23 19:24'
labels: []
milestone: Power MCU stock Zephyr power trial
dependencies:
  - TASK-12.2
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
  - devices/power/mcu
  - devices/power/README.md
parent_task_id: TASK-12
ordinal: 20000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Power customizations are made only after Task 2 baseline measurements are recorded.
- [ ] #2 REDCON protocol, BLE identity/NVE format, manual OpenOCD flashing commands, and power-device behavior remain unchanged.
- [ ] #3 just power::mcu::check, build, check-flash, and check-nve power-test all succeed after customization.
- [ ] #4 The user manually flashes and re-measures current after customization.
- [ ] #5 Task notes record each power-focused customization and before/after current measurements; success is best-effort reduction, not a fixed numeric threshold.
<!-- AC:END -->
