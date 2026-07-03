---
id: TASK-7
title: Throttle BLE background GATT refreshes
status: Done
assignee:
  - codex
created_date: '2026-05-23 09:50'
updated_date: '2026-05-23 09:51'
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
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Background BLE GATT refreshes should not monopolize the per-device connection path after every advertisement. Advertisement-only reachability must publish promptly, while connected reads should run only when active state is stale enough or required by inventory startup, keeping command latency from queueing behind redundant background reads.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Advertisement scan callbacks no longer schedule background GATT reads while a recent state read is fresh.
- [x] #2 Inventory cached-address refreshes skip devices with fresh connected state.
- [x] #3 Command paths still bypass the background freshness throttle.
- [x] #4 Rig Go tests cover fresh-state background refresh suppression.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Fold recent state-read freshness and active per-device connects into the background refresh scheduler.
2. Keep advertisement capability/shadow publication immediate, but avoid starting redundant GATT reads from scan and inventory while state is fresh.
3. Add focused scheduler tests, run rig Go tests, then close the task.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The 11:48 log showed background GATT reads repeatedly taking the per-device BLE connect path for several seconds after advertisements and inventory refreshes, including duplicate weather reads and a unit read that delayed state publish by about five seconds. The background scheduler now skips when a per-device connect is active, a command hold is active, or the last connected state read is still within the active measurement freshness window. Advertisement capability/shadow publication remains immediate, and command code calls the GATT path directly rather than through this background scheduler.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Background GATT refreshes are now throttled by recent state freshness and active per-device connects, reducing redundant reads that can queue operator commands. Added tests for fresh-state and active-connect suppression. Verified with go test ./... in rig.
<!-- SECTION:FINAL_SUMMARY:END -->
