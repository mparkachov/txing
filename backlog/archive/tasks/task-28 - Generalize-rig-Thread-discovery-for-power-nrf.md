---
id: TASK-28
title: Generalize rig Thread discovery for power-nrf
status: Done
assignee:
  - '@codex'
created_date: '2026-08-01 12:23'
updated_date: '2026-08-01 13:57'
labels: []
milestone: m-5
dependencies: []
documentation:
  - >-
    backlog/docs/architecture/power-nrf-thread-device/doc-33 -
    power-nrf-Thread-device-architecture.md
modified_files:
  - rig/internal/thread/protocol.go
  - rig/internal/thread/discovery.go
  - rig/internal/thread/otctl.go
  - rig/internal/thread/runtime.go
  - rig/internal/thread/protocol_test.go
type: feature
ordinal: 74000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Enable the existing Thread rig runtime to operate with power-si and power-nrf while enforcing enlisted device identity.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Inventory entries retain their expected type for both supported device types.
- [x] #2 DNS-SD discovery accepts power-si and power-nrf TXT types and rejects unsupported types.
- [x] #3 A discovered endpoint is used only when its TXT type matches the enlisted device type.
- [x] #4 CoAP REDCON confirmation and Thread Power capability publication work for both types.
- [x] #5 Existing power-si MQTT and shadow topic behavior is unchanged.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Represent the enlisted Thread device type in the runtime specification, accept exactly power-si and power-nrf discovery TXT types, and retain endpoints only when their TXT type matches inventory. Extend mixed-type tests across discovery, polling, REDCON confirmation, capabilities, and unchanged power-si shadow topics.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Generalized the Thread adapter for power-si and power-nrf. Inventory specs retain their device type, DNS-SD and ot-ctl SRP discovery accept only those two TXT types, and runtime endpoint admission requires an exact inventory/TXT type match. Added mixed-device, mismatch, REDCON-confirmation, capability, and shadow-topic coverage; go test ./... passes from rig/.
<!-- SECTION:FINAL_SUMMARY:END -->
