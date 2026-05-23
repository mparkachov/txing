---
id: TASK-11
title: 'Milestone: Go unit board daemon replacement'
status: Done
assignee: []
created_date: '2026-05-23 14:30'
updated_date: '2026-05-23 16:29'
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
- [x] #1 The unit board daemon is built and released from Go as txing-unit-daemon with the same public runtime contract.
- [x] #2 The native KVS worker active name is txing-unit-kvs-master across build, release, install, and docs.
- [x] #3 The common board systemd target is txing-unit.target and rollout notes cover old unit cleanup.
- [x] #4 Rust is retired from the active unit daemon build/release surface after parity validation passes.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Milestone closeout audit confirms all child tasks are Done and the active unit board runtime surface now uses the Go txing-unit-daemon, txing-unit-kvs-master, and txing-unit.target. Release workflow builds the Go daemon asset with DaemonVersion injection; release/versioning checks no longer manage devices/unit/daemon/Cargo.toml; active docs include manual cleanup for txing-board.target and txing-board-kvs-master.service. TASK-11.5 removed the remaining tracked Rust daemon source, Cargo, build.rs, and Rust Docker builder files.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Go unit board daemon replacement is complete. The public txing-unit-daemon name and asset are built from Go with injected version support, the native KVS worker and board target use txing-unit-kvs-master and txing-unit.target, rollout docs cover old board target/service cleanup, and the Rust unit daemon build/release surface has been retired. Final validation passed for Go daemon tests/build, KVS native CTest, release version checking, shared release/versioning unittest coverage, formatting whitespace checks, and targeted stale-reference searches.
<!-- SECTION:FINAL_SUMMARY:END -->
