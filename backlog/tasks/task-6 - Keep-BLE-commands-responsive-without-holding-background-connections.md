---
id: TASK-6
title: Keep BLE commands responsive without holding background connections
status: Done
assignee:
  - codex
created_date: '2026-05-23 09:36'
updated_date: '2026-05-23 09:37'
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
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
BLE background observation must release connections so scan refreshes continue, but command-initiated active REDCON transitions should keep a short warm connection window so follow-up operator actions do not wait for the MCU advertising rendezvous.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Background GATT refreshes still disconnect immediately after publishing state.
- [x] #2 Successful active BLE commands keep the connection warm briefly and then release it automatically.
- [x] #3 Idle REDCON commands release immediately so the device can return to sleep-state advertising.
- [x] #4 Rig Go tests cover command hold/release policy decisions.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add an explicit connection release policy so background reads and idle commands disconnect immediately.
2. For successful active BLE commands, schedule a short bounded delayed disconnect that can be superseded by a newer command.
3. Prevent background refreshes from stealing a command-held connection.
4. Add focused unit tests for policy selection and hold tracking, then run rig Go tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The 0.11.5 follow-up made the shared GATT path disconnect after every read, which fixed background scan freshness but also made active operator commands lose the warm BLE connection. Added an explicit release policy: background reads and REDCON 4 commands disconnect immediately, while successful active BLE commands keep the connection for a bounded 15 seconds. Hold tokens ensure an older timer cannot disconnect a newer command hold, and background refreshes skip while a command hold is active.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
BLE command handling now keeps active REDCON transitions responsive with a short bounded connection hold, while background refreshes and idle commands still release immediately. Added tests for release policy and hold token supersession. Verified with go test ./... in rig.
<!-- SECTION:FINAL_SUMMARY:END -->
