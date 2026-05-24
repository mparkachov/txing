---
id: TASK-15
title: 'Milestone: Unit MCU stock Zephyr migration'
status: To Do
assignee: []
created_date: '2026-05-24 13:21'
labels: []
milestone: Unit MCU stock Zephyr migration
dependencies:
  - TASK-14
references:
  - devices/common/mcu
  - devices/unit/mcu
  - devices/unit/aws/ble-shadow.schema.json
  - devices/unit/aws/power-shadow.schema.json
documentation:
  - >-
    backlog/docs/architecture/mcu-stock-zephyr-shared-stack/doc-6 -
    MCU-stock-Zephyr-shared-stack-migration.md
  - >-
    backlog/docs/constraints/mcu-stock-zephyr-shared-stack/doc-7 -
    Constraints-MCU-stock-Zephyr-shared-stack.md
  - >-
    backlog/docs/milestones/unit-mcu-stock-zephyr-migration/doc-10 -
    Milestone-Unit-MCU-stock-Zephyr-migration.md
  - docs/contracts/unit-device-contracts.md
  - devices/unit/docs/device-rig-shadow-spec.md
ordinal: 23000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 unit::mcu check/build/paths/clean use the shared stock Zephyr stack and no active unit build path depends on NCS.
- [ ] #2 Stock-incompatible NCS-only configuration is removed while preserving unit REDCON 1/2/3/4, D1 power, battery, BLE identity, and NVE behavior.
- [ ] #3 Rig-facing Sparkplug and named-shadow semantics remain compatible with the current unit contracts.
- [ ] #4 check-flash unit and check-nve unit-test print direct OpenOCD commands without programming hardware.
- [ ] #5 User manual validation after flashing confirms REDCON transitions through the rig/web workflow as hardware allows.
- [ ] #6 Obsolete unit MCU generated build/cache/workspace folders and any unit-specific NCS wrapper are removed once the shared stock Zephyr build is validated.
<!-- AC:END -->
