---
id: TASK-23.13
title: unattended board provisioning is validated on physical hardware
status: To Do
assignee: []
created_date: '2026-07-25 17:44'
labels: []
milestone: m-4
dependencies:
  - TASK-23.9
  - TASK-23.12
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 69000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Operator-run validation closing the consolidation, mirroring TASK-23.7's role for the musl migration. Agents prepare commands and evidence templates; the operator executes all on-device steps, including writing cards and reimaging the remaining Debian board. This is where the merged implementation, the unified protocol, the single runbook, and the unattended installer are proven together on real hardware.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A cyberbrick board provisioned from a generated card reaches REDCON 1 with live video and working motion control, with no ssh session used before the board is up.
- [ ] #2 A unit board provisioned the same way reaches the same state, confirming the merged implementation works for both device types.
- [ ] #3 The board previously running the Debian build is reimaged to Alpine and rejoins service on the unified protocol.
- [ ] #4 Evidence for every board is recorded in the task's implementation notes.
<!-- AC:END -->
