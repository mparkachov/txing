---
id: TASK-21.6
title: synchronize per-device MQTT sessions with DDEATH and DBIRTH lifecycle
status: To Do
assignee: []
created_date: '2026-07-19 13:01'
updated_date: '2026-07-19 13:01'
labels: []
milestone: m-0
dependencies:
  - TASK-21.3
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
- [ ] #1 When BLE or Thread capability evidence makes a device Sparkplug-unavailable, the manager publishes exactly one DDEATH and closes that device MQTT client.
- [ ] #2 An unavailable device does not recreate its per-device MQTT connection on the manager publication tick; the AWS Things Console shows it disconnected.
- [ ] #3 Fresh validated BLE GATT or Thread CoAP evidence creates a new per-device MQTT client and publishes DBIRTH with the recovered capability state.
- [ ] #4 Rig node MQTT connectivity and unrelated device sessions remain available while one device is offline.
- [ ] #5 Tests cover unavailable-to-DDEATH-and-disconnect, no reconnect without evidence, and recovered-evidence-to-new-session-and-DBIRTH for BLE and Thread states.
<!-- AC:END -->

## Definition of Done

<!-- DOD:BEGIN -->
No Definition of Done items defined
<!-- DOD:END -->
