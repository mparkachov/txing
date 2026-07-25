---
id: TASK-23.9
title: board video bridge speaks one protocol package
status: To Do
assignee: []
created_date: '2026-07-25 17:43'
labels: []
milestone: m-4
dependencies:
  - TASK-23.8
references:
  - docs/contracts/board-video-bridge.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 65000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The local daemon-to-worker video bridge contract is duplicated per device, so even a merged implementation would carry a device axis in its wire contract. Unify it onto one device-independent package. This renames the gRPC service, so a board running a mixed pair stops connecting and video goes down silently: the worker retries a bridge that never answers and the daemon logs to CloudWatch rather than locally. The Debian board pinned to the last Debian-built KVS master cannot be rebuilt, because camera builds are Alpine-only, so it must be reimaged to Alpine before this lands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The daemon and KVS master communicate over a single device-independent bridge protocol on both device types.
- [ ] #2 Upgrading a board installs the daemon, hardware worker, and KVS master together, and the runbook states that a partial upgrade leaves video down with no local error.
- [ ] #3 No board remains in service running a build that speaks the previous per-device protocol.
<!-- AC:END -->
