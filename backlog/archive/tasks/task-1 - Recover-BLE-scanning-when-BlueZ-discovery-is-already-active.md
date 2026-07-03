---
id: TASK-1
title: Recover BLE scanning when BlueZ discovery is already active
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 08:13'
updated_date: '2026-05-23 08:15'
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
  - rig/internal/ble/runtime.go
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Raspberry Pi rig BLE connectivity daemon must recover from BlueZ reporting scan discovery as already active without requiring a service restart or letting BLE capability state go stale in Office.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 When BlueZ reports scan discovery is already in progress, txing-ble-connectivity uses a short bounded recovery path rather than exponential backoff to 120 seconds.
- [x] #2 The scan/connect handoff does not require a txing-ble-connectivity service restart to resume publishing fresh BLE capability state.
- [x] #3 Relevant rig Go tests cover the retry classification and scan-loop delay decision.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a scan retry decision helper that treats BlueZ 'operation already in progress' as scan handoff recovery with a short bounded delay.
2. Use that helper in txing-ble-connectivity scanLoop so stale discovery does not climb to the generic 120s retry cap.
3. Add focused Go tests for retry classification and the log-observable delay behavior, then run rig tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented scan retry recovery for BlueZ already-active discovery. The scan loop now stops stale discovery, resets scan failure count, and retries after 1000ms while preserving generic exponential backoff for other scan failures. Validated with go test ./... using repo-local Go caches.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
txing-ble-connectivity now treats BlueZ 'Operation already in progress' during scan startup as a recoverable stale-discovery handoff: it stops discovery, resets retry failures, and retries after a short fixed delay. Added tests for the already-active recovery decision and generic backoff behavior.
<!-- SECTION:FINAL_SUMMARY:END -->
