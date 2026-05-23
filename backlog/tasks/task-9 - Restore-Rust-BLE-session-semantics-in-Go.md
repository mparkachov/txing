---
id: TASK-9
title: Restore Rust BLE session semantics in Go
status: Done
assignee:
  - codex
created_date: '2026-05-23 13:35'
updated_date: '2026-05-23 13:58'
labels: []
milestone: rig BLE reliability
dependencies: []
references:
  - rig/cmd/txing-ble-connectivity/main.go
  - rig/cmd/txing-ble-connectivity/main_test.go
documentation:
  - docs/contracts/unit-device-contracts.md
  - devices/unit/docs/device-rig-shadow-spec.md
modified_files:
  - rig/cmd/txing-ble-connectivity/main.go
  - rig/cmd/txing-ble-connectivity/session.go
  - rig/cmd/txing-ble-connectivity/main_test.go
  - rig/internal/ble/runtime.go
  - rig/internal/ble/runtime_test.go
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Go BLE connectivity daemon should restore the old Rust BLE runtime semantics: each managed BLE device has one long-lived session that owns advertisements, command handling, connected state, reconnect backoff, and aggregate sample publication. Passive scan/background work must not race active wake commands or repeatedly churn GATT service discovery.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Inventory reconciliation starts/stops one BLE session per managed device and command dispatch goes through that device session instead of spawning independent command goroutines.
- [x] #2 Scan advertisements are delivered to sessions, cached before inventory when necessary, and ignored by a session while it has a live connection so advertisement-only state cannot downgrade connected state.
- [x] #3 Background connection attempts belong to the session and use per-session reconnect backoff; active commands wait for connection capacity and reuse an already connected device when available.
- [x] #4 Connected sessions keep aggregate REDCON/measurement state, publish a connected-state heartbeat without shadow updates, and age only stale measurements using the Rust active/idle freshness windows.
- [x] #5 Command connect retry behavior waits for fresh advertisements when needed and publishes accepted/succeeded/failed results from the session.
- [x] #6 Focused Go tests cover session routing, connected advertisement suppression, command-capacity behavior, retry/fresh-advertisement behavior, and measurement staleness.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Introduce a per-device session type with advertisement and command channels, Rust-equivalent local state, and bounded reconnect/backoff helpers.
2. Move inventory reconciliation and command dispatch to session routing, leaving the scanner as the producer of advertisement events.
3. Replace one-shot background goroutines with session-owned background connect logic and persistent connected device reuse.
4. Add aggregate sample publication, heartbeat, stale measurement aging, notification handling where the Go Bluetooth API supports it, and Rust-style command retry/wait-for-fresh-ad behavior.
5. Update tests around the new session state model and run rig Go tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Restored the Rust session model in Go by adding one long-lived `deviceSession` per managed BLE device. Sessions own advertisement evidence, command serialization, connected state, reconnect backoff, notification drain, connected-state heartbeat, aggregate REDCON/measurement publication, and active/idle measurement staleness. Runtime inventory reconciliation now creates/removes sessions and routes commands into the matching session. Scanner events cache full advertisements before inventory and deliver throttled advertisements into sessions after inventory. Commands reuse an already connected BLE device and, when no fresh advertisement exists, wait for the next matching advertisement before retrying the connection path. The retry classifier now treats Rust-era transient advertisement/visibility failures as retryable.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The Go BLE connectivity daemon now follows the old Rust semantics: per-device sessions, persistent connection reuse, notification-driven state updates, session-owned background connects, fresh-ad command retry, connected advertisement suppression, and Rust active/idle measurement freshness. Verified with `go test ./...` from `rig/`.
<!-- SECTION:FINAL_SUMMARY:END -->
