---
id: TASK-21.6
title: synchronize per-device MQTT sessions with DDEATH and DBIRTH lifecycle
status: Done
assignee:
  - '@root'
created_date: '2026-07-19 13:01'
updated_date: '2026-07-27 20:12'
labels: []
milestone: m-0
dependencies: []
references:
  - rig/cmd/txing-sparkplug-manager/main.go
  - rig/internal/manager/manager.go
parent_task_id: TASK-21
priority: high
ordinal: 48500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Synchronize each rig-owned per-device AWS MQTT session with the device Sparkplug lifecycle so the AWS IoT Things Console connection status does not contradict Office transport availability. When BLE GATT or Thread CoAP becomes unavailable, the manager must publish DDEATH and close that device's MQTT proxy session. Fresh validated transport evidence must establish a new proxy session before DBIRTH. The rig node MQTT session remains independent.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 When BLE or Thread capability evidence makes a device Sparkplug-unavailable, the manager publishes exactly one DDEATH and closes that device MQTT client.
- [x] #2 An unavailable device does not recreate its per-device MQTT connection on the manager publication tick; the AWS Things Console shows it disconnected.
- [x] #3 Fresh validated BLE GATT or Thread CoAP evidence creates a new per-device MQTT client and publishes DBIRTH with the recovered capability state.
- [x] #4 Rig node MQTT connectivity and unrelated device sessions remain available while one device is offline.
- [x] #5 Tests cover unavailable-to-DDEATH-and-disconnect, no reconnect without evidence, and recovered-evidence-to-new-session-and-DBIRTH for BLE and Thread states.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
No Definition of Done items defined
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Inspect the current per-device MQTT lifecycle and tests; make device session ownership follow validated Sparkplug availability; add focused BLE and Thread recovery tests; run the rig manager test suite and document manual rollout.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented evidence-gated per-device MQTT sessions. Inventory refresh and idle publication ticks no longer create device clients. BLE GATT or Thread CoAP unavailability emits DDEATH, disconnects and clears only that device client; fresh validated evidence creates a new client before DBIRTH. Added BLE and Thread lifecycle/recovery tests, including node and unrelated-session isolation. Validation passed: go test -race ./cmd/txing-sparkplug-manager ./internal/manager; go vet ./...; just rig::test.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed TASK-21.6: per-device AWS IoT MQTT sessions now follow validated Sparkplug availability. Offline BLE/Thread devices publish one DDEATH and disconnect; publication ticks do not reconnect them; recovered evidence creates a new client then DBIRTH with recovered capabilities. Rig node and unrelated device sessions remain independent. Documented the lifecycle contract and added focused BLE/Thread tests. Validation: race-enabled manager tests, go vet, and full rig test recipe pass.
<!-- SECTION:FINAL_SUMMARY:END -->
