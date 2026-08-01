---
id: TASK-26
title: Implement power-nrf Thread SED CoAP firmware
status: To Do
assignee: []
created_date: '2026-08-01 12:23'
labels: []
milestone: m-5
dependencies: []
documentation:
  - >-
    backlog/docs/architecture/power-nrf-thread-device/doc-33 -
    power-nrf-Thread-device-architecture.md
type: feature
ordinal: 72000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deliver the standalone stock-Zephyr Thread firmware application for XIAO nRF54LM20A, without Matter or BLE dependencies.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Firmware exposes version-1 GET state and PUT redcon CoAP endpoints and accepts only REDCON levels 3 and 4.
- [ ] #2 It registers SRP service _txing-coap._udp on port 5683 with TXT type=power-nrf and pv=1.
- [ ] #3 It attaches and registers in receiver-on mode, then operates as MTD SED with a 5000 ms poll interval.
- [ ] #4 REDCON 3 switches Thread to rn and enables D1 plus blue led0; REDCON 4 disables both, responds, then returns Thread to n.
- [ ] #5 Release and SED-debug recovery remain bounded and SED-only; ordinary debug retains receiver-on diagnostics.
- [ ] #6 Build and source assertions prove Matter CHIP and BLE REDCON are absent.
<!-- AC:END -->
