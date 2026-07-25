---
id: TASK-23.12
title: a freshly imaged card provisions the board on first boot
status: To Do
assignee: []
created_date: '2026-07-25 17:44'
labels: []
milestone: m-4
dependencies:
  - TASK-23.11
references:
  - docs/components/cyberbrick-board.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 68000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Fresh board install is a long interactive sequence: a console login, interactive base setup, manual partitioning and sys install, then every runtime step by hand over ssh. Make the generated card carry its own provisioning so a board becomes operational by being written and powered on. Alpine's boot model forces two stages: the Raspberry Pi image boots diskless into tmpfs, a 512 MB board cannot hold the runtime package set there, and converting to a sys install copies the running root onto the card and stops applying the overlay afterwards.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A board written with a generated card reaches a running, network-reachable persistent install with no console login and no interactive setup.
- [ ] #2 First-boot provisioning installs runtime packages, device enumeration, camera support, release binaries, device configuration, and services without operator commands.
- [ ] #3 Provisioning leaves the root filesystem writable and does not seal the board read-only, so a board that provisioned incorrectly stays recoverable.
- [ ] #4 Interrupting or repeating provisioning does not corrupt an already-provisioned board.
- [ ] #5 The provisioning steps and the runbook stay consistent with each other rather than drifting into two descriptions of the same install.
<!-- AC:END -->
