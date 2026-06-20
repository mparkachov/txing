---
id: TASK-21
title: 'Milestone: power-si Thread device type'
status: To Do
assignee: []
created_date: '2026-06-20 07:12'
labels: []
milestone: m-0
dependencies: []
references:
  - devices/power/manifest.toml
  - devices/common/mcu/scripts/stock_zephyr_mcu.py
  - rig/internal/protocol
  - tmp/ot_ping/ot_ping.ino
documentation:
  - >-
    backlog/docs/architecture/power-si-thread-device/doc-21 -
    power-si-Thread-device-type-architecture.md
  - >-
    backlog/docs/milestones/power-si-thread-device/doc-22 -
    Milestone-power-si-Thread-device-type.md
priority: high
ordinal: 44000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deliver power-si as a first-class txing device type equivalent to the current power device, using XIAO MG24 stock Zephyr/OpenThread and Thread/CoAP transport through a new rig connectivity daemon. Implementation must proceed through child tasks and must not run firmware flashing, factory programming, AWS mutation, or OTBR setup commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 power-si implementation is split into scoped child tasks for catalog/UI, firmware/provisioning, rig runtime, and release/acceptance.
- [ ] #2 The milestone preserves existing nRF power/BLE behavior and existing TXR1 NVE semantics.
- [ ] #3 Completion evidence includes automated test results plus documented manual hardware acceptance steps for a user-run board/OTBR setup.
<!-- AC:END -->
