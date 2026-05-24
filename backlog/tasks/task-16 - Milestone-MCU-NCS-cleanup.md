---
id: TASK-16
title: 'Milestone: MCU NCS cleanup'
status: To Do
assignee: []
created_date: '2026-05-24 13:22'
labels: []
milestone: MCU NCS cleanup
dependencies:
  - TASK-15
references:
  - devices/common/mcu
  - devices/power/mcu
  - devices/weather/mcu
  - devices/unit/mcu
  - .gitmodules
documentation:
  - >-
    backlog/docs/architecture/mcu-stock-zephyr-shared-stack/doc-6 -
    MCU-stock-Zephyr-shared-stack-migration.md
  - >-
    backlog/docs/constraints/mcu-stock-zephyr-shared-stack/doc-7 -
    Constraints-MCU-stock-Zephyr-shared-stack.md
  - >-
    backlog/docs/milestones/mcu-ncs-cleanup/doc-11 -
    Milestone-MCU-NCS-cleanup.md
  - docs/components/mcu.md
ordinal: 24000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Obsolete active NCS build paths, per-device NCS wrappers, and generated NCS workspace docs are removed or retired.
- [ ] #2 The modules/nrfconnect/sdk-nrf submodule and its .gitmodules entry are removed after all active MCU targets build on stock Zephyr.
- [ ] #3 MCU component docs, device MCU READMEs, and agent guidance describe stock Zephyr as the active MCU stack.
- [ ] #4 power, weather, and unit MCU builds pass on the shared stock Zephyr stack after cleanup.
- [ ] #5 Source and documentation searches show no active NCS command path remains for active MCU builds.
<!-- AC:END -->
