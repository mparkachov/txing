---
id: TASK-11
title: 'Milestone: Go unit board daemon replacement'
status: To Do
assignee: []
created_date: '2026-05-23 14:30'
labels: []
milestone: Go unit board daemon replacement
dependencies: []
references:
  - devices/unit/daemon
  - devices/unit/board/kvs_master
  - .github/workflows/release.yml
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
ordinal: 11000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The unit board daemon is built and released from Go as txing-unit-daemon with the same public runtime contract.
- [ ] #2 The native KVS worker active name is txing-unit-kvs-master across build, release, install, and docs.
- [ ] #3 The common board systemd target is txing-unit.target and rollout notes cover old unit cleanup.
- [ ] #4 Rust is retired from the active unit daemon build/release surface after parity validation passes.
<!-- AC:END -->
