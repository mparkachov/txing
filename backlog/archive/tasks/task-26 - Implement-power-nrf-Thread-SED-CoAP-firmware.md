---
id: TASK-26
title: Implement power-nrf Thread SED CoAP firmware
status: Done
assignee:
  - '@codex'
created_date: '2026-08-01 12:23'
updated_date: '2026-08-01 13:10'
labels: []
milestone: m-5
dependencies: []
documentation:
  - >-
    backlog/docs/architecture/power-nrf-thread-device/doc-33 -
    power-nrf-Thread-device-architecture.md
modified_files:
  - devices/power-nrf/mcu/src/main.c
  - devices/power-nrf/mcu/zephyr/CMakeLists.txt
  - devices/power-nrf/mcu/zephyr/Kconfig
  - devices/power-nrf/mcu/zephyr/prj.conf
  - devices/power-nrf/mcu/zephyr/debug.conf
  - devices/power-nrf/mcu/zephyr/sed-debug.conf
  - devices/power-nrf/mcu/zephyr/release.conf
  - >-
    devices/power-nrf/mcu/zephyr/boards/xiao_nrf54lm20a_nrf54lm20a_cpuapp.overlay
  - devices/common/mcu/tests/test_power_nrf_sed_config.py
type: feature
ordinal: 72000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deliver the standalone stock-Zephyr Thread firmware application for XIAO nRF54LM20A, without Matter or BLE dependencies.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Firmware exposes version-1 GET state and PUT redcon CoAP endpoints and accepts only REDCON levels 3 and 4.
- [x] #2 It registers SRP service _txing-coap._udp on port 5683 with TXT type=power-nrf and pv=1.
- [x] #3 It attaches and registers in receiver-on mode, then operates as MTD SED with a 5000 ms poll interval.
- [x] #4 REDCON 3 switches Thread to rn and enables D1 plus blue led0; REDCON 4 disables both, responds, then returns Thread to n.
- [x] #5 Release and SED-debug recovery remain bounded and SED-only; ordinary debug retains receiver-on diagnostics.
- [x] #6 Build and source assertions prove Matter CHIP and BLE REDCON are absent.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Adapt the established power-si stock-Zephyr Thread architecture into a standalone LM20A application, retaining only the version-1 CoAP, SRP, SED lifecycle, and REDCON behavior needed for power-nrf. Read TXN1 factory data from the new partition, configure 5000 ms MTD SED operation, and make REDCON transitions switch D1/led0 plus rn/n after the response. Keep release and SED-debug recovery bounded and sleepy-only, retain receiver-on diagnostics in ordinary debug, and add source/build assertions that exclude Matter and BLE.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented standalone stock-Zephyr power-nrf Thread/CoAP firmware with TXN1 loading, SRP registration, five-second MTD SED lifecycle, REDCON D1/led0 rn/n transitions, bounded profile-specific recovery, and Matter/BLE exclusion assertions. Validated release, debug, and SED-debug LM20A ELFs plus 35 focused MCU tests.
<!-- SECTION:FINAL_SUMMARY:END -->
