---
id: TASK-5
title: Preserve BLE advertisements seen before inventory
status: Done
assignee:
  - codex
created_date: '2026-05-23 09:16'
updated_date: '2026-05-23 09:18'
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
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
BLE scanning can see Txing advertisements before the inventory subscription has delivered managed device specs. The daemon must retain those observed addresses and schedule the first bounded refresh once inventory arrives so BlueZ cache/replay behavior cannot leave managed devices absent from UI until a service restart or external bluetoothctl scan.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Txing service advertisements with a local name are cached even when inventory has not yet marked the name as managed.
- [x] #2 Inventory reconciliation schedules background GATT refreshes for newly managed devices that already have a cached BLE address.
- [x] #3 Rig Go tests cover the pre-inventory advertisement cache path.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Cache Txing service advertisement addresses by advertised local name before checking inventory membership.
2. During inventory reconciliation, schedule background refreshes for managed specs that already have cached addresses.
3. Add focused tests around the cache/scheduling helper behavior, run rig Go tests, then close the Backlog task.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The 0.11.5 startup log showed scan discovery before inventory reconciliation, so the daemon ignored a Txing advertisement as unmanaged and could miss BlueZ replay after inventory arrived. The scan path now records Txing service addresses by local name before inventory membership is checked, and inventory reconciliation returns cached-address refresh candidates that schedule bounded background connects.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
BLE connectivity now preserves pre-inventory advertisements and schedules the first background refresh after inventory arrives for managed devices with cached addresses. Added tests for pre-inventory address caching and cached-address inventory refresh candidates. Verified with go test ./... in rig.
<!-- SECTION:FINAL_SUMMARY:END -->
