---
id: TASK-25
title: Add power-nrf stock-Zephyr builds and factory provisioning
status: Done
assignee:
  - '@codex'
created_date: '2026-08-01 12:23'
updated_date: '2026-08-01 12:49'
labels: []
milestone: m-5
dependencies: []
documentation:
  - >-
    backlog/docs/architecture/power-nrf-thread-device/doc-33 -
    power-nrf-Thread-device-architecture.md
modified_files:
  - devices/common/mcu/scripts/stock_zephyr_mcu.py
  - devices/common/mcu/tests/test_stock_zephyr_mcu.py
  - devices/common/mcu/xiao_nrf54lm20a/scripts/thread_factory.py
  - devices/common/mcu/xiao_nrf54lm20a/tests/test_txn1_factory.py
  - devices/power-nrf/justfile
  - devices/power-nrf/mcu/justfile
  - devices/power-nrf/mcu/zephyr
  - docs/components/mcu.md
type: feature
ordinal: 71000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Extend the shared MCU driver for the upstream XIAO nRF54LM20A target and provide independently provisioned TXN1 factory records.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Release, debug, and SED-debug builds target xiao_nrf54lm20a/nrf54lm20a/cpuapp with stock Zephyr and stock OpenOCD.
- [x] #2 The driver provides dedicated power-nrf build directories and a power-nrf::mcu::nve Thing-name and dataset command.
- [x] #3 TXN1 records validate magic version bounds CRC32 and factory partition limits and generate correctly addressed Intel HEX.
- [x] #4 The 36 KiB storage region is split into an 8 KiB read-only factory partition and a 28 KiB OpenThread settings partition.
- [x] #5 Existing TXR1 and TXT1 formats and commands remain compatible.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Inspect the shared stock-Zephyr driver and the existing TXT1 factory pipeline. Add a power-nrf board configuration for the exact upstream LM20A target, separate release/debug/SED-debug build directories, and stock OpenOCD runner arguments. Implement a separate TXN1 writer and Intel-HEX command with 8 KiB factory and 28 KiB OpenThread-settings boundaries, then expose it through power-nrf::mcu::nve. Add focused tests that preserve TXT1/TXR1 behavior and validate the new format and command generation.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added the power-nrf LM20A stock-Zephyr driver configuration, release/debug/SED-debug build profiles, stock board OpenOCD command, dedicated Just recipes, TXN1 parser/writer, Intel-HEX generation, and the 8 KiB factory plus 28 KiB OpenThread settings partition overlay. Existing TXR1/TXT1 paths remain covered by the shared MCU test suite.
<!-- SECTION:FINAL_SUMMARY:END -->
