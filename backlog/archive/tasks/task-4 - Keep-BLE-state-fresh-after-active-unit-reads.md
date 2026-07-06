---
id: TASK-4
title: Keep BLE state fresh after active unit reads
status: Done
assignee:
  - codex
created_date: '2026-05-23 09:06'
updated_date: '2026-05-23 09:09'
labels: []
milestone: rig BLE reliability
dependencies: []
references:
  - rig/cmd/txing-ble-connectivity/main.go
  - rig/internal/ble/runtime.go
documentation:
  - docs/contracts/unit-device-contracts.md
  - devices/unit/docs/device-rig-shadow-spec.md
modified_files:
  - rig/cmd/txing-ble-connectivity/main.go
  - rig/cmd/txing-ble-connectivity/main_test.go
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The BLE daemon must not let advertisement-only evidence overwrite a fresh connected state read, and it must continue refreshing unit capability state after REDCON wake so SparkplugManager does not publish DDEATH while BLE is still reachable.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A fresh unit/power state read with power=true is not immediately downgraded by advertisement-only capability state from the same BLE adapter.
- [x] #2 After a background GATT read, the daemon releases the BLE connection so subsequent advertisements can trigger bounded refreshes before SparkplugManager's state TTL expires.
- [x] #3 Rig Go tests cover advertisement publish suppression after a recent state read.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Track the timestamp of successful connected BLE state reads per thing.
2. Suppress advertisement-only capability-state publishes for unit/power devices while that connected state is still fresh.
3. Always release the BLE connection after a background read so scan callbacks can continue to refresh state.
4. Add focused tests for suppression and weather behavior, then run rig Go tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Observed logs showed connected GATT reads publishing power=true/redcon=3, followed immediately by advertisement-only capability state publishing power=false and empty metrics for the same unit. Added a per-thing timestamp for successful connected reads, suppressing unit/power advertisement-only capability state while the connected read is fresh. Also disconnects after each GATT read so BlueZ can resume scan callbacks and schedule bounded refreshes.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
BLE connectivity now preserves fresh connected unit state against immediate advertisement-only downgrades, releases GATT connections after reads, and has focused tests for recent-read suppression plus weather advertisement behavior. Verified with go test ./... in rig.
<!-- SECTION:FINAL_SUMMARY:END -->
