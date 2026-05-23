---
id: TASK-11.2
title: Implement Go daemon runtime parity
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 14:30'
updated_date: '2026-05-23 15:27'
labels: []
milestone: Go unit board daemon replacement
dependencies:
  - TASK-11.1
references:
  - docs/contracts/unit-device-contracts.md
  - docs/contracts/board-video-bridge.md
  - docs/contracts/unit-hardware-worker.md
documentation:
  - >-
    backlog/docs/architecture/unit-daemon-go-reimplementation/doc-1 -
    Unit-daemon-Go-reimplementation.md
  - >-
    backlog/docs/milestones/go-unit-board-daemon-replacement/doc-2 -
    Milestone-Go-unit-board-daemon-replacement.md
  - >-
    backlog/docs/constraints/unit-board-daemon-go-parity/doc-3 -
    Constraints-unit-board-daemon-Go-parity.md
modified_files:
  - devices/unit/daemon/cmd/txing-unit-daemon/main.go
  - devices/unit/daemon/go.mod
  - devices/unit/daemon/go.sum
  - devices/unit/daemon/internal/daemon/runtime.go
  - devices/unit/daemon/internal/daemon/runtime_test.go
parent_task_id: TASK-11
ordinal: 13000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The Go daemon publishes the same board, capability, MCP, and video MQTT/shadow payloads as the current daemon for equivalent runtime events.
- [x] #2 The Go daemon preserves AWS IoT temporary credential fetching, Sparkplug REDCON shadow read, MQTT mTLS connection behavior, and CloudWatch Logs writer semantics.
- [x] #3 The Go daemon serves BoardVideoBridge over the same Unix socket and talks to UnitHardware over the same client socket with matching timeout/degrade behavior.
- [x] #4 MCP active-control, transport switching, command delegation, watchdog cleanup, and shutdown/offline behavior match the current daemon.
- [x] #5 Ported Go tests cover all current Rust daemon runtime behavior areas, including gRPC Unix-socket integration and hardware-worker delegation.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Port the Rust daemon runtime primitives into the existing Go module: logging helpers, AWS IoT credential fetching, CloudWatch Logs writer behavior, MQTT publisher/subscription behavior, capability/board/video/MCP payload publication, and runtime state transitions without changing public topics, shadows, payload shapes, env names, sockets, or proto contracts.
2. Implement the BoardVideoBridge and UnitHardware integrations in Go over the existing generated protobuf bindings, preserving Unix socket paths, timeout/degrade behavior, worker credential vending, video state reporting, MCP session forwarding, and hardware stop/apply/status delegation semantics.
3. Port MCP runtime behavior into Go: descriptor/status publication, JSON-RPC handling, active-control takeover/epoch checks, transport switching between MQTT and WebRTC bridge sessions, watchdog expiration, command delegation, and offline/shutdown cleanup.
4. Add Go parity tests matching the current Rust daemon behavior areas, including publication payloads, AWS credential and CloudWatch writer edge cases, MQTT/shadow behavior, BoardVideoBridge Unix-socket integration, UnitHardware delegation, MCP active-control behavior, watchdog cleanup, and shutdown/offline publication.
5. Run focused Go tests throughout, then run the relevant existing Rust daemon tests as the parity baseline; leave Rust daemon removal, active release-surface rewiring, KVS rename, and systemd target rename to later milestone tasks unless TASK-11.2 acceptance criteria require a narrow compatibility touch.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented Go runtime parity coverage for TASK-11.2: runtime state publication, retained capability state, board/MCP/video shadow updates, MCP JSON-RPC active control, video transport switching, BoardVideoBridge gRPC over Unix sockets, UnitHardware gRPC client delegation, AWS IoT temporary credential fetching/parsing, Sparkplug REDCON parsing, MQTT mTLS packet loop, CloudWatch Logs writer setup/retry helpers, and signal-driven daemon runtime entrypoint. Added Go parity tests covering these runtime behavior areas.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-11.2 ports the unit daemon runtime behavior into Go behind the existing txing-unit-daemon command. The Go runtime now reads Sparkplug REDCON through AWS IoT Data using IoT certificate-derived temporary credentials, connects MQTT over mTLS on port 8883, publishes board/capability/MCP/video state, serves BoardVideoBridge over the configured Unix socket, delegates motion to UnitHardware over its Unix socket, enforces MCP active-control semantics, switches MCP transport when video becomes ready, and publishes offline state during shutdown. Go parity tests cover publication payloads, MCP control/command behavior, video transport switching, bridge Unix-socket integration, hardware delegation, IoT credential helpers, Sparkplug REDCON parsing, and CloudWatch writer retry semantics. Validation: go test ./... passed with workspace-local Go caches; cargo test --lib passed 50/50 Rust baseline tests; injected Go version build printed txing-unit-daemon 9.8.7-test.
<!-- SECTION:FINAL_SUMMARY:END -->
