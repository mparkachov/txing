---
id: TASK-29
title: Validate and document power-nrf rollout
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
type: task
ordinal: 75000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Provide reproducible validation coverage and an operator handoff for deploying a Power nRF device.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Automated Go and firmware tests cover mixed-type discovery, type matching, contracts, factory records, SED modes, and battery failure behavior.
- [ ] #2 Release, debug, and SED-debug images build against an updated stock Zephyr checkout and the exact stock OpenOCD command is verified.
- [ ] #3 The operator README documents user-run catalog deployment, enlistment, factory provisioning, manual flashing, and OTBR daemon enablement.
- [ ] #4 Hardware acceptance criteria document SRP registration, SED mode and poll interval, router role, REDCON transitions, PMIC telemetry, and Office-visible state.
<!-- AC:END -->
