---
id: doc-3
title: 'Constraints: unit board daemon Go parity'
type: guide
created_date: '2026-05-23 14:29'
updated_date: '2026-05-23 14:30'
---
# Constraints: Unit Board Daemon Go Parity

## Behavioral Constraints
- Preserve daemon public behavior exactly unless a future task records an approved contract change.
- Preserve existing proto files and wire contracts for BoardVideoBridge and UnitHardware.
- Preserve retained MQTT topic roots, shadow update topics, shadow payload shapes, MCP protocol, MCP tool names, active-control semantics, and JSON-RPC error codes/messages.
- Preserve config precedence: CLI, process env, env file, then defaults.
- Preserve runtime reliability properties: bounded retries, graceful degradation, deterministic shutdown/offline publication, and no retry storms.

## Naming Constraints
- Keep daemon name `txing-unit-daemon` and asset `txing-unit-daemon-linux-aarch64.tar.gz`.
- Rename KVS worker active surfaces to `txing-unit-kvs-master`.
- Rename common board runtime target to `txing-unit.target`.
- Do not rename the KVS signaling channel pattern `<thing-id>-board-video` or `TXING_BOARD_VIDEO_*` env variables.

## Operational Constraints
- Do not run AWS mutation commands.
- Do not deploy to boards, flash firmware, or add automatic board migration scripts.
- Board rollout remains manual: release assets, root-owned `mise`, root-writable maintenance window, systemd edits, sync, reboot, and verification.
- Documentation must include manual cleanup for old `txing-board.target` and `txing-board-kvs-master.service` when upgrading existing boards.

## Test Constraints
- Port the Rust daemon coverage before removing the Rust daemon from active build/release paths.
- Keep test acceptance outcome-based: behavior parity matters more than matching old internal Rust symbol names.
- Release/versioning tests must assert the new KVS asset/service/target names and absence of old active names.
