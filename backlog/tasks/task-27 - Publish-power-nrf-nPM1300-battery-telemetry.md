---
id: TASK-27
title: Publish power-nrf nPM1300 battery telemetry
status: Done
assignee:
  - '@codex'
created_date: '2026-08-01 12:23'
updated_date: '2026-08-01 13:48'
labels: []
milestone: m-5
dependencies: []
documentation:
  - >-
    backlog/docs/architecture/power-nrf-thread-device/doc-33 -
    power-nrf-Thread-device-architecture.md
modified_files:
  - devices/power-nrf/mcu/src/main.c
  - devices/power-nrf/mcu/zephyr/prj.conf
  - devices/common/mcu/tests/test_power_nrf_sed_config.py
  - rig/internal/thread/protocol.go
  - rig/internal/thread/protocol_test.go
type: feature
ordinal: 73000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Expose measured XIAO nRF54LM20A battery millivolts through the existing power named shadow.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Battery voltage is read on demand through the nPM1300 measurement interface.
- [x] #2 A valid reading is published as batteryMv without invented conversions or fallback values.
- [x] #3 Unavailable or failed measurements publish batteryMv: null.
- [x] #4 Firmware and named-shadow tests cover valid, unavailable, and failed measurement behavior.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Inspect the existing power-si battery pipeline and upstream nPM1300 measurement driver, add on-demand LM20A measurement to the standalone firmware state response without fallback values, then cover valid/unavailable/failed results in firmware and named-shadow tests.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added on-demand nPM1300 charger-sensor battery reads to power-nrf state responses. Valid sensor readings are emitted as batteryMv; unavailable or failed reads emit null and the Thread adapter now publishes that null to the existing power named shadow. Added firmware and named-shadow coverage for valid, unavailable, and failed paths; validated the stock-LM20A release build.
<!-- SECTION:FINAL_SUMMARY:END -->
