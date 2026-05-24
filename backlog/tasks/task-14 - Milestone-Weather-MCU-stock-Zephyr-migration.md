---
id: TASK-14
title: 'Milestone: Weather MCU stock Zephyr migration'
status: To Do
assignee: []
created_date: '2026-05-24 13:21'
labels: []
milestone: Weather MCU stock Zephyr migration
dependencies:
  - TASK-13
references:
  - devices/common/mcu
  - devices/weather/mcu
  - devices/weather/mcu/README.md
documentation:
  - >-
    backlog/docs/architecture/mcu-stock-zephyr-shared-stack/doc-6 -
    MCU-stock-Zephyr-shared-stack-migration.md
  - >-
    backlog/docs/constraints/mcu-stock-zephyr-shared-stack/doc-7 -
    Constraints-MCU-stock-Zephyr-shared-stack.md
  - >-
    backlog/docs/milestones/weather-mcu-stock-zephyr-migration/doc-9 -
    Milestone-Weather-MCU-stock-Zephyr-migration.md
ordinal: 22000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 weather::mcu check/build/paths/clean use the shared stock Zephyr stack and no active weather build path depends on NCS.
- [ ] #2 Stock-incompatible NCS-only configuration is removed while preserving weather REDCON 4, BME280, battery, D1 power, and NVE behavior.
- [ ] #3 check-flash weather and check-nve weather-test print direct OpenOCD commands without programming hardware.
- [ ] #4 User manual validation after flashing confirms BLE identity, REDCON service, weather measurement, and battery measurement behavior.
<!-- AC:END -->
