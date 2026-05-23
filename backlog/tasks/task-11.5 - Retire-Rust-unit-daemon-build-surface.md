---
id: TASK-11.5
title: Retire Rust unit daemon build surface
status: To Do
assignee: []
created_date: '2026-05-23 14:30'
labels: []
milestone: Go unit board daemon replacement
dependencies:
  - TASK-11.4
references:
  - devices/unit/daemon/Cargo.toml
  - devices/unit/daemon/src/lib.rs
  - devices/unit/daemon/src/main.rs
documentation:
  - >-
    backlog/docs/milestones/go-unit-board-daemon-replacement/doc-2 -
    Milestone-Go-unit-board-daemon-replacement.md
  - >-
    backlog/docs/constraints/unit-board-daemon-go-parity/doc-3 -
    Constraints-unit-board-daemon-Go-parity.md
parent_task_id: TASK-11
ordinal: 16000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Rust daemon source, Cargo files, build.rs, and Rust-specific Docker/release build surfaces are removed or made inactive after Go parity tests pass.
- [ ] #2 No active build, release, versioning, or install path depends on Cargo for txing-unit-daemon.
- [ ] #3 Search confirms old Rust daemon active references are gone or retained only as explicit historical/migration notes.
- [ ] #4 Final validation runs Go daemon tests, KVS native tests, and release/versioning checks relevant to the unit board runtime.
<!-- AC:END -->
