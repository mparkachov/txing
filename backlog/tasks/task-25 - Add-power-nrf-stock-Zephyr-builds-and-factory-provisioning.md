---
id: TASK-25
title: Add power-nrf stock-Zephyr builds and factory provisioning
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
ordinal: 71000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Extend the shared MCU driver for the upstream XIAO nRF54LM20A target and provide independently provisioned TXN1 factory records.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Release, debug, and SED-debug builds target xiao_nrf54lm20a/nrf54lm20a/cpuapp with stock Zephyr and stock OpenOCD.
- [ ] #2 The driver provides dedicated power-nrf build directories and a power-nrf::mcu::nve Thing-name and dataset command.
- [ ] #3 TXN1 records validate magic version bounds CRC32 and factory partition limits and generate correctly addressed Intel HEX.
- [ ] #4 The 36 KiB storage region is split into an 8 KiB read-only factory partition and a 28 KiB OpenThread settings partition.
- [ ] #5 Existing TXR1 and TXT1 formats and commands remain compatible.
<!-- AC:END -->
