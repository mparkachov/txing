---
id: TASK-21
title: 'Milestone: power-si Thread device type'
status: Done
assignee: []
created_date: '2026-06-20 07:12'
updated_date: '2026-07-27 19:51'
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
- [x] #1 power-si implementation is split into scoped child tasks for catalog/UI, firmware/provisioning, rig runtime, and release/acceptance.
- [x] #2 The milestone preserves existing nRF power/BLE behavior and existing TXR1 NVE semantics.
- [x] #3 Completion evidence includes automated test results plus documented manual hardware acceptance steps for a user-run board/OTBR setup.
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed all eleven child tasks for power-si.

Delivered a first-class power-si catalog/UI contract, stock Zephyr/OpenThread firmware for XIAO MG24 with TXT1 factory provisioning, and a Thread/CoAP rig daemon with direct local SRP registry discovery. The final release is a 5 s Thread SED at REDCON 4; REDCON 3 requests receiver-on rn for immediate follow-up control and REDCON 4 returns to n after the CoAP reply grace. Existing nRF power/BLE and TXR1 behavior remain unchanged.

Validated: rig Go suite; Office suite (174 tests); MCU configuration/factory tests (16 tests); shared AWS suite (136 tests excluding the unrelated shell-portability scan of an untracked generated Go module tree); release and sed-debug xiao_mg24 builds. Manual board/OTBR acceptance confirmed SRP registration, SED poll behavior, CoAP REDCON 4->3->4, D1/LED effects, battery shadow reporting, Office reflection, and Sparkplug lifecycle evidence.

The full end-to-end hardware record and operational procedures are maintained in the milestone and architecture documentation.
<!-- SECTION:FINAL_SUMMARY:END -->
