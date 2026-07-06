---
id: TASK-8
title: Stop passive unit GATT reads from blocking wake
status: Done
assignee:
  - codex
created_date: '2026-05-23 11:26'
updated_date: '2026-05-23 11:27'
labels: []
milestone: rig BLE reliability
dependencies: []
references:
  - rig/cmd/txing-ble-connectivity/main.go
documentation:
  - docs/contracts/unit-device-contracts.md
  - devices/unit/docs/device-rig-shadow-spec.md
modified_files:
  - rig/cmd/txing-ble-connectivity/main.go
  - rig/cmd/txing-ble-connectivity/main_test.go
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sleeping unit advertisements already prove BLE reachability and let Sparkplug select REDCON 4. Passive unit GATT reads from startup or frequent stale checks can block active wake commands for many seconds when DiscoverServices times out. The BLE daemon should avoid passive unit GATT reads before a connected state exists and refresh connected unit state only on the longer idle freshness cadence.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Power/unit advertisements do not schedule passive background GATT reads before any connected state has been read.
- [x] #2 After a connected unit state read, advertisement-only capability state and passive background refresh use the idle freshness window instead of the 20s active measurement window.
- [x] #3 Command paths still connect directly and are not blocked by the passive background scheduler.
- [x] #4 Debug logs show received and completed BLE commands.
- [x] #5 Rig Go tests cover passive unit background suppression before first connected read and the longer suppression window.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Change passive background scheduling to take the device spec so unit/power devices can be handled differently from weather devices.
2. Suppress passive unit GATT reads until a connected state read exists, then use the idle freshness window for both advertisement-state suppression and passive refresh.
3. Add debug command lifecycle logs.
4. Update focused tests and run rig Go tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The 0.11.8 log showed a sleeping unit advertisement immediately scheduling a cached-address passive GATT read before any command. That read timed out in DiscoverServices, and later passive reads repeated every 20s. The scheduler now takes the device spec: unit/power devices do not start passive background GATT reads before any connected state read exists, and once a connected state exists both advertisement-only capability-state suppression and passive background refresh use the 120s idle freshness window. Commands still call connectAndPublishCommand directly. Added debug logs for command received/succeeded/failed so the next deployed log clearly shows whether the wake command reaches BLE connectivity.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Passive unit GATT reads no longer block wake from startup advertisements, and connected unit state is preserved/refreshed on the longer idle freshness cadence. Added command debug lifecycle logs and tests for pre-read suppression plus the longer freshness window. Verified with go test ./... in rig.
<!-- SECTION:FINAL_SUMMARY:END -->
