---
id: TASK-2
title: Publish BLE reachability from unit advertisements
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 08:39'
updated_date: '2026-05-23 08:39'
labels: []
milestone: rig BLE reliability
dependencies: []
references:
  - rig/cmd/txing-ble-connectivity/main.go
  - rig/internal/ble/runtime.go
  - rig/internal/ble/protocol.go
documentation:
  - docs/contracts/unit-device-contracts.md
  - devices/unit/docs/device-rig-shadow-spec.md
modified_files:
  - rig/internal/ble/runtime.go
  - rig/internal/ble/runtime_test.go
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The rig BLE connectivity daemon must publish fresh Sparkplug BLE capability state when a managed unit/power device advertisement is observed, so Office shows BLE reachability even before or without a successful GATT state read.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Managed unit/power advertisements publish capability state with sparkplug=true and ble=true while keeping power unavailable until a state read confirms wakeup power.
- [x] #2 Weather advertisement behavior remains available at REDCON 4 with weather capability as before.
- [x] #3 Rig Go tests cover power/unit advertisement capability-state publication.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Change advertisement capability publication so managed unit/power advertisements publish fresh BLE reachability state.
2. Preserve power=false and no bleRedcon metric for advertisement-only unit/power evidence, so REDCON can resolve to 4 without pretending wakeup power is available.
3. Update focused rig tests and run go test ./... with repo-local Go caches.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Published capability state for all managed BLE advertisements. Advertisement samples already carry sparkplug=true and ble=true with power=false for unit/power devices and REDCON 4 metrics for weather devices. Validated with go test ./... using repo-local Go caches.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Managed unit/power advertisements now refresh BLE reachability capability state, allowing SparkplugManager and Office to show BLE availability before a GATT state read succeeds. Weather advertisement behavior remains unchanged.
<!-- SECTION:FINAL_SUMMARY:END -->
