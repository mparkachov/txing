---
id: TASK-11.3
title: Rename unit KVS worker and board runtime target
status: To Do
assignee: []
created_date: '2026-05-23 14:30'
labels: []
milestone: Go unit board daemon replacement
dependencies: []
references:
  - devices/unit/board/kvs_master
  - docs/components/board.md
  - docs/artifacts.md
documentation:
  - >-
    backlog/docs/milestones/go-unit-board-daemon-replacement/doc-2 -
    Milestone-Go-unit-board-daemon-replacement.md
  - >-
    backlog/docs/constraints/unit-board-daemon-go-parity/doc-3 -
    Constraints-unit-board-daemon-Go-parity.md
parent_task_id: TASK-11
ordinal: 14000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The active native KVS worker executable, CMake target, test target, release asset, service name, mise alias, and docs use txing-unit-kvs-master.
- [ ] #2 The daemon-served KVS worker client id and worker default client identity use txing-unit-kvs-master while the KVS signaling channel remains <thing-id>-board-video.
- [ ] #3 Active board systemd docs and tests use txing-unit.target with txing-unit-daemon.service, txing-unit-kvs-master.service, and txing-unit-hardware-worker.service.
- [ ] #4 Upgrade notes describe manual cleanup of old txing-board.target and txing-board-kvs-master.service on deployed boards.
<!-- AC:END -->
