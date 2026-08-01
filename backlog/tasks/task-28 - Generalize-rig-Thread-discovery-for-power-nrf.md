---
id: TASK-28
title: Generalize rig Thread discovery for power-nrf
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
ordinal: 74000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Enable the existing Thread rig runtime to operate with power-si and power-nrf while enforcing enlisted device identity.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Inventory entries retain their expected type for both supported device types.
- [ ] #2 DNS-SD discovery accepts power-si and power-nrf TXT types and rejects unsupported types.
- [ ] #3 A discovered endpoint is used only when its TXT type matches the enlisted device type.
- [ ] #4 CoAP REDCON confirmation and Thread Power capability publication work for both types.
- [ ] #5 Existing power-si MQTT and shadow topic behavior is unchanged.
<!-- AC:END -->
