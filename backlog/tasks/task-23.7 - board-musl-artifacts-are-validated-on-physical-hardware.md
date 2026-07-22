---
id: TASK-23.7
title: board musl artifacts are validated on physical hardware
status: To Do
assignee: []
created_date: '2026-07-21 09:01'
updated_date: '2026-07-22 20:32'
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
- [x] #1 The static unit daemon and hardware worker from an Alpine-built unit release run on a physical Debian (Raspberry Pi OS) board with normal daemon operation, and the pinned last Debian-built KVS master still functions there.
- [ ] #2 The full board stack including the musl-dynamic KVS master runs on a physical Alpine board installed from the documented runbook, with read-only root and OpenRC autostart unaffected.
- [ ] #3 Evidence for both boards is recorded in the task's implementation notes.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
AC1 evidence - physical Debian board (Raspberry Pi Zero 2 W 'txing', Raspberry Pi OS trixie, kernel 6.18.33+rpt-rpi-v8, aarch64), operator-run 2026-07-22:

Baseline: all three unit tools at 0.14.14 (last Debian-built release); mise conf.d config with version_prefix unit-v; board healthy with viewer connected.

Detour found and fixed during validation: (1) first upgrade pulled unit-v0.15.4, which was Debian-built because the cyberbrick branch with the Alpine migration had never been pushed - the dispatched workflow ran the old Debian pipeline from the remote; hardware worker ldd showed glibc/grpc/protobuf dynamic linkage. (2) After pushing, the Alpine build job failed: JavaScript actions (checkout/upload-artifact) cannot run inside musl containers on arm64 runners. Fixed in both release-unit.yml and release-cyberbrick.yml by running the build job on the host and driving the pinned alpine:3.23.5 container via docker exec heredocs with workspace/temp mounted at identical paths; step bodies and container-side gates unchanged; test_versioning.py 21 passed + 8 subtests without test edits. This also means the cyberbrick release workflow had never run successfully before this fix.

Upgrade (writable-root window): mise upgrade of the static pair to Alpine-built unit-v0.15.6. Post-upgrade checks: txing-unit-daemon 0.15.6 ldd 'not a dynamic executable'; txing-unit-hardware-worker 0.15.6 ldd 'statically linked' (static-pie); txing-unit-kvs-master pinned at 0.14.14, ldd resolves libcamera.so.0.7 and libcamera-base.so.0.7.

Post-reboot: root filesystem ro; txing-unit.target and all three services active in the fresh boot; daemon logs version 0.15.6; frozen KVS master 0.14.14 streaming - TXING_VIEWER_CONNECTED and TXING_MCP_DATACHANNEL_OPEN within ~8s of service start. Note: hardware worker systemd start time displays as May 23 due to Pi no-RTC clock skew at early boot (before chrony sync); the current-boot journal logs version 0.15.6 for it, proving the new static binary is the running one.
<!-- SECTION:NOTES:END -->
