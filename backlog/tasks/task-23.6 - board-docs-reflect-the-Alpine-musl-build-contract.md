---
id: TASK-23.6
title: board docs reflect the Alpine musl build contract
status: To Do
assignee: []
created_date: '2026-07-21 09:01'
labels: []
milestone: m-4
dependencies:
  - TASK-23.3
  - TASK-23.4
references:
  - docs/components/board.md
  - docs/artifacts.md
  - docs/components/cyberbrick-board.md
  - docs/installation.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
  - >-
    backlog/docs/constraints/board-musl-static-builds/doc-32 -
    Constraints-board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 62000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Update board documentation for the Alpine build contract and the Debian transition: unit's runbook drops Debian-build and libcamera 0.7 expectations for new artifacts, documents the static daemon and hardware worker linkage checks, and states that camera updates are Alpine-only with Debian boards pinned to the last Debian-built KVS master until reimaged to Alpine.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 docs/components/board.md documents the new artifact ABI (static daemon and hardware worker; Alpine-only musl-dynamic KVS master), replaces the libcamera 0.7 ldd checks accordingly, and adds transition guidance for existing Debian boards including the camera freeze.
- [ ] #2 docs/artifacts.md and docs/installation.md describe the unified Alpine build contract for unit and cyberbrick artifacts.
- [ ] #3 docs/components/cyberbrick-board.md linkage guidance matches the static daemon and hardware worker policy.
<!-- AC:END -->
