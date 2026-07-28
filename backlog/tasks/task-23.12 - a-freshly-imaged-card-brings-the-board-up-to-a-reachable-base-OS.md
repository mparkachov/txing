---
id: TASK-23.12
title: a freshly imaged card brings the board up to a reachable base OS
status: To Do
assignee: []
created_date: '2026-07-25 17:44'
updated_date: '2026-07-28 06:43'
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
Fresh board install is a long interactive sequence before any txing-specific work starts: a console login, interactive base setup, then manual partitioning and sys install. Make the generated card carry its own base provisioning so a board becomes network-reachable over ssh by being written and powered on, and the operator picks up the existing runbook at the mise step. Alpine's boot model forces two stages: the Raspberry Pi image boots diskless into tmpfs, and converting to a sys install copies the running root onto the card and stops applying the overlay afterwards. Provisioning ends at a plain, current base OS — on Wi-Fi, repositories enabled, packages upgraded, root key installed — and deliberately goes no further.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A board written with a generated card reaches a persistent sys install on the standard Raspberry Pi partition layout, with no console login and no interactive setup.
- [ ] #2 First boot brings up wlan0 networking, enables the apk repositories the runbook needs, applies available package upgrades, and accepts operator ssh as root with the provisioned key.
- [ ] #3 Provisioning stops at that base state: mise, runtime packages, udev, camera support, release binaries, device configuration, and services remain manual runbook steps run over ssh.
- [ ] #4 Provisioning leaves the root filesystem writable and does not seal the board read-only, so a board that provisioned incorrectly stays recoverable.
- [ ] #5 Interrupting or repeating provisioning does not corrupt an already-provisioned board.
- [ ] #6 The provisioning steps and the runbook stay consistent with each other rather than drifting into two descriptions of the same install.
<!-- AC:END -->
