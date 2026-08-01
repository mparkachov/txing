---
id: TASK-24
title: Integrate power-nrf contracts and control plane
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
ordinal: 70000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deliver power-nrf as a first-class raspi device type with the same Sparkplug, Thread, Power, and REDCON contract as power-si.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Device manifests, defaults, and Sparkplug Thread Power named-shadow contracts define power-nrf.
- [ ] #2 Catalog, enlistment, CloudFormation type catalog, root just module, and Office registry adapter accept Power nRF.
- [ ] #3 REDCON 4 publishes Sparkplug and Thread, while REDCON 3 additionally publishes Power.
- [ ] #4 Existing power and power-si behavior remains unchanged and integration tests cover the new type.
<!-- AC:END -->
