---
id: TASK-23.5
title: board artifacts run on both Debian and Alpine hosts
status: To Do
assignee: []
created_date: '2026-07-21 09:01'
labels: []
milestone: m-4
dependencies:
  - TASK-23.2
  - TASK-23.3
  - TASK-23.4
references:
  - .github/workflows/release-unit.yml
  - .github/workflows/release-cyberbrick.yml
  - devices/unit/daemon/justfile
  - devices/cyberbrick/daemon/justfile
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 61000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Prove the transition promise in CI and locally: the static daemon and hardware worker execute on both Debian and Alpine userlands, and the KVS master executes on Alpine. Both release workflows gain cross-distro smoke steps and the justfiles gain a matching local recipe.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Both release workflows execute each built daemon and hardware worker binary in debian:trixie and pinned alpine:3.23.5 linux/arm64 containers (version or startup smoke) and the KVS master in the Alpine container only, failing the release on any smoke failure.
- [ ] #2 A justfile recipe reproduces the same cross-distro smoke locally via docker run for unit and cyberbrick artifacts.
<!-- AC:END -->
