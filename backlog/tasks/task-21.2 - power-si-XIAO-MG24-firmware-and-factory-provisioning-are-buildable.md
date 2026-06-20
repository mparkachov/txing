---
id: TASK-21.2
title: power-si XIAO MG24 firmware and factory provisioning are buildable
status: To Do
assignee: []
created_date: '2026-06-20 07:12'
labels: []
milestone: m-0
dependencies:
  - TASK-21.1
references:
  - devices/common/mcu/scripts/stock_zephyr_mcu.py
  - tmp/ot_ping/ot_ping.ino
documentation:
  - >-
    backlog/docs/architecture/power-si-thread-device/doc-21 -
    power-si-Thread-device-type-architecture.md
parent_task_id: TASK-21
priority: high
ordinal: 46000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Provide the stock Zephyr/OpenThread firmware and nonvolatile factory provisioning surface for the XIAO MG24 power-si device without changing existing nRF power firmware or TXR1 NVE semantics.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 power-si MCU firmware builds for stock Zephyr board xiao_mg24 with OpenThread Thread end-device behavior, no Matter stack, D1 power output, active-low LED state, and CoAP state/REDCON resources.
- [ ] #2 TXT1 factory data generation stores Thing name, Thread Active Operational Dataset TLVs, CoAP port, and CRC in a dedicated MG24 factory partition while Zephyr/OpenThread settings use a separate aligned storage partition.
- [ ] #3 Input validation rejects missing or invalid Thing names, malformed/oversized TLVs, and records that exceed the factory partition.
- [ ] #4 Existing power/nRF build, flash-check, and TXR1 NVE command behavior remains covered and unchanged.
- [ ] #5 Validation records the MCU build/check commands run and does not run hardware flashing or factory programming commands.
<!-- AC:END -->
