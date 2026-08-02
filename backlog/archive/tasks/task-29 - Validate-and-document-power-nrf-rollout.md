---
id: TASK-29
title: Validate and document power-nrf rollout
status: Done
assignee: []
created_date: '2026-08-01 12:23'
updated_date: '2026-08-02 11:09'
labels: []
milestone: m-5
dependencies: []
documentation:
  - >-
    backlog/docs/architecture/power-nrf-thread-device/doc-33 -
    power-nrf-Thread-device-architecture.md
modified_files:
  - devices/power-nrf/README.md
  - >-
    backlog/docs/architecture/power-nrf-thread-device/doc-33 -
    power-nrf-Thread-device-architecture.md
type: task
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Provide reproducible validation coverage and an operator handoff for deploying a Power nRF device.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Automated Go and firmware tests cover mixed-type discovery, type matching, contracts, factory records, SED modes, and battery failure behavior.
- [x] #2 Release, debug, and SED-debug images build against an updated stock Zephyr checkout and the exact stock OpenOCD command is verified.
- [x] #3 The operator README documents user-run catalog deployment, enlistment, factory provisioning, manual flashing, and OTBR daemon enablement.
- [x] #4 Hardware acceptance criteria document SRP registration, SED mode and poll interval, router role, REDCON transitions, PMIC telemetry, and Office-visible state.
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Automated Go and firmware coverage passed, and release, debug, and SED-debug images were built with the stock LM20A Zephyr/OpenOCD path. The operator README and architecture record now preserve the hardware result: TXN1 provisioning, receiver-on attachment, SRP registration, and non-router child role were observed, but no reliable CoAP/indirect delivery was validated after the required transition to SED mode n, even at very short range. REDCON, PMIC telemetry, and Office acceptance were consequently not reached. The XIAO nRF54LM20A Sense external-antenna requirement is incompatible with the target enclosure; this task closes as a documented product limitation and does not authorize deployment.
<!-- SECTION:FINAL_SUMMARY:END -->
