---
id: TASK-27
title: Publish power-nrf nPM1300 battery telemetry
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
ordinal: 73000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Expose measured XIAO nRF54LM20A battery millivolts through the existing power named shadow.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Battery voltage is read on demand through the nPM1300 measurement interface.
- [ ] #2 A valid reading is published as batteryMv without invented conversions or fallback values.
- [ ] #3 Unavailable or failed measurements publish batteryMv: null.
- [ ] #4 Firmware and named-shadow tests cover valid, unavailable, and failed measurement behavior.
<!-- AC:END -->
