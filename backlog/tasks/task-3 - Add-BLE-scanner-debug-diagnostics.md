---
id: TASK-3
title: Add BLE scanner debug diagnostics
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 08:52'
updated_date: '2026-05-23 08:53'
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
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
When TXING_RIG_DEBUG=true is set, txing-ble-connectivity must log enough scanner and publish-path detail to diagnose why Linux-visible BLE peripherals are not appearing in Office.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Debug logs show relevant scan candidates, including txing-prefixed names, whether the txing service UUID was present, and whether the candidate matched inventory.
- [x] #2 Debug logs show successful BLE capability-state publication and background connect failures/successes.
- [x] #3 Normal info-level runtime remains quiet unless TXING_RIG_DEBUG=true is set.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add small debug helper methods on runtimeState so TXING_RIG_DEBUG gates all new scanner diagnostics.
2. Log relevant scan candidates and reasons for ignoring them: missing txing service, empty name, unmanaged inventory, matched/published.
3. Log capability-state publish success and background connect result, then run focused rig tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added TXING_RIG_DEBUG-gated scanner diagnostics for relevant candidates, ignored reasons, published advertisement state, capability-state publish success, and background connect result. Validated with go test ./... using repo-local Go caches.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
txing-ble-connectivity now emits scanner and publish-path diagnostics only when TXING_RIG_DEBUG=true, making Linux-visible but Office-missing BLE devices diagnosable without noisy normal logs.
<!-- SECTION:FINAL_SUMMARY:END -->
