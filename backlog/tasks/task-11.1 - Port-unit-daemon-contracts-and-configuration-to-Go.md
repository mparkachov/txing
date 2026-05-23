---
id: TASK-11.1
title: Port unit daemon contracts and configuration to Go
status: To Do
assignee: []
created_date: '2026-05-23 14:30'
labels: []
milestone: Go unit board daemon replacement
dependencies: []
references:
  - devices/unit/daemon
  - devices/unit/proto/txing/unit/board_video/v1/board_video.proto
  - devices/unit/proto/txing/unit/hardware/v1/unit_hardware.proto
  - devices/unit/daemon/daemon.env.template
documentation:
  - >-
    backlog/docs/architecture/unit-daemon-go-reimplementation/doc-1 -
    Unit-daemon-Go-reimplementation.md
  - >-
    backlog/docs/constraints/unit-board-daemon-go-parity/doc-3 -
    Constraints-unit-board-daemon-Go-parity.md
parent_task_id: TASK-11
ordinal: 12000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A Go module and txing-unit-daemon command exist under devices/unit/daemon and preserve the existing --version behavior with injected release version support.
- [ ] #2 Go protobuf bindings are generated from the existing BoardVideoBridge and UnitHardware proto files without changing wire contracts.
- [ ] #3 Config parsing preserves existing CLI flags, TXING_* env names, env-file loading, precedence, defaults, validation, and colocated certificate behavior.
- [ ] #4 Ported Go tests cover the current configuration, topic-building, env parsing, version, and static payload behavior.
<!-- AC:END -->
