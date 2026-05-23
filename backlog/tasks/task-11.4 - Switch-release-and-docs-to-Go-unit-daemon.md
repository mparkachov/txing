---
id: TASK-11.4
title: Switch release and docs to Go unit daemon
status: To Do
assignee: []
created_date: '2026-05-23 14:30'
labels: []
milestone: Go unit board daemon replacement
dependencies:
  - TASK-11.1
  - TASK-11.2
  - TASK-11.3
references:
  - .github/workflows/release.yml
  - release/src/txing_release/cli.py
  - shared/aws/python/tests/test_versioning.py
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
ordinal: 15000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Release workflow builds, tests, packages, and publishes the Go txing-unit-daemon asset with version injection and no Cargo unit-daemon job.
- [ ] #2 Release workflow packages txing-unit-kvs-master-linux-aarch64.tar.gz and all release notes/checks refer to the new KVS asset name.
- [ ] #3 Versioning and documentation tests assert the Go daemon, txing-unit-kvs-master, and txing-unit.target active surfaces.
- [ ] #4 Current board, artifacts, installation, and component docs describe the Go daemon and manual board rollout steps.
<!-- AC:END -->
