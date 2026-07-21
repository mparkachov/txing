---
id: TASK-23.7
title: board musl artifacts are validated on physical hardware
status: To Do
assignee: []
created_date: '2026-07-21 09:01'
labels: []
milestone: m-4
dependencies:
  - TASK-23.5
  - TASK-23.6
references:
  - docs/components/board.md
  - docs/components/cyberbrick-board.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 63000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Operator-run validation closing the milestone, mirroring TASK-22.6's role for m-3: the migrated artifacts are exercised on real boards. Agents prepare commands and evidence templates; the operator executes all on-device steps.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The static unit daemon and hardware worker from an Alpine-built unit release run on a physical Debian (Raspberry Pi OS) board with normal daemon operation, and the pinned last Debian-built KVS master still functions there.
- [ ] #2 The full board stack including the musl-dynamic KVS master runs on a physical Alpine board installed from the documented runbook, with read-only root and OpenRC autostart unaffected.
- [ ] #3 Evidence for both boards is recorded in the task's implementation notes.
<!-- AC:END -->
