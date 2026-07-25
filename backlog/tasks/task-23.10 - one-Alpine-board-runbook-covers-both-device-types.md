---
id: TASK-23.10
title: one Alpine board runbook covers both device types
status: To Do
assignee: []
created_date: '2026-07-25 17:43'
labels: []
milestone: m-4
dependencies:
  - TASK-23.8
references:
  - docs/components/board.md
  - docs/components/cyberbrick-board.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 66000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Board documentation is split by accident of history rather than by content: the unit runbook is Debian and systemd, the cyberbrick runbook is Alpine and OpenRC, and the two duplicate most of their install and maintenance steps while differing only in names and OS commands. Unit on Alpine is therefore undocumented. Consolidate into one Alpine runbook covering both device types, and freeze the Debian material for the boards not yet reimaged. Note that the unit runbook also holds the device-agnostic board behavior contract that the cyberbrick runbook delegates to, so the split is by content, not by file.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A single board runbook covers fresh install, maintenance, and troubleshooting for both device types on Alpine, with device-specific values collected in one place rather than spread through the prose.
- [ ] #2 The device-agnostic board behavior contract remains available and the device documents that delegate to it still resolve.
- [ ] #3 Debian and systemd install and maintenance instructions remain available as clearly frozen material and are no longer presented as current practice.
- [ ] #4 The documentation index and all cross-references resolve, and documentation tests reflect the new structure.
<!-- AC:END -->
