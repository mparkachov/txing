---
id: TASK-11.2
title: Implement Go daemon runtime parity
status: To Do
assignee: []
created_date: '2026-05-23 14:30'
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
parent_task_id: TASK-11
ordinal: 13000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The Go daemon publishes the same board, capability, MCP, and video MQTT/shadow payloads as the current daemon for equivalent runtime events.
- [ ] #2 The Go daemon preserves AWS IoT temporary credential fetching, Sparkplug REDCON shadow read, MQTT mTLS connection behavior, and CloudWatch Logs writer semantics.
- [ ] #3 The Go daemon serves BoardVideoBridge over the same Unix socket and talks to UnitHardware over the same client socket with matching timeout/degrade behavior.
- [ ] #4 MCP active-control, transport switching, command delegation, watchdog cleanup, and shutdown/offline behavior match the current daemon.
- [ ] #5 Ported Go tests cover all current Rust daemon runtime behavior areas, including gRPC Unix-socket integration and hardware-worker delegation.
<!-- AC:END -->
