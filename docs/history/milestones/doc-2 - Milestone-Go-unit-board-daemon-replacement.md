---
id: doc-2
title: 'Milestone: Go unit board daemon replacement'
type: guide
created_date: '2026-05-23 14:29'
updated_date: '2026-05-23 14:30'
---
# Milestone: Go Unit Board Daemon Replacement

## Outcome
The unit board daemon is implemented in Go, shipped under the existing `txing-unit-daemon` public name, and the Rust daemon is removed from the active unit build/release surface. The KVS worker and systemd common target use the new unit naming.

## Scope
- Go daemon implementation and tests with parity against the current Rust suite.
- Active release workflow, version checker, local build recipes, and docs use the Go daemon.
- Native KVS worker is renamed to `txing-unit-kvs-master` across active source/build/release/docs surfaces.
- Board runtime documentation uses `txing-unit.target` with the three services: daemon, KVS master, and hardware worker.

## Non-goals
- No new daemon functionality, protocols, schemas, topics, MQTT contract changes, BLE behavior, AWS infrastructure changes, or board hardware automation.
- No automated deployment to boards and no firmware flashing.
- No backwards-compatible parallel Rust/Go daemon mode.

## Dependencies
- Existing unit contracts in `docs/contracts/unit-device-contracts.md`, `docs/contracts/board-video-bridge.md`, and `docs/contracts/unit-hardware-worker.md`.
- Existing shadow schemas in `devices/unit/aws/*-shadow.schema.json`.
- Current release and versioning checks.

## Validation
- Go daemon tests cover the same 50 behavior areas currently covered by Rust tests.
- KVS native CTest target passes after rename.
- Shared release/versioning tests pass after asset, service, target, and docs updates.
- Search confirms old KVS binary/service/target names appear only in explicit migration notes.

## Exit Criteria
- `txing-unit-daemon` builds from Go and reports the injected release version.
- Release artifacts include `txing-unit-daemon-linux-aarch64.tar.gz`, `txing-unit-kvs-master-linux-aarch64.tar.gz`, and `txing-unit-hardware-worker-linux-aarch64.tar.gz`.
- Active docs and tests describe `txing-unit.target` and `txing-unit-kvs-master`.
- Rust daemon code and Cargo-based unit daemon release paths are no longer active.
