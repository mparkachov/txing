---
id: TASK-22.6
title: cyberbrick board reaches unit parity on hardware
status: To Do
assignee: []
created_date: '2026-07-15 07:38'
labels: []
milestone: m-3
dependencies:
  - TASK-22.2
  - TASK-22.4
  - TASK-22.5
references:
  - docs/components/board.md
  - docs/sparkplug-lifecycle.md
documentation:
  - >-
    backlog/docs/architecture/cyberbrick-device-type/doc-27 -
    Cyberbrick-device-type-architecture.md
  - >-
    backlog/docs/constraints/cyberbrick-alpine-board/doc-29 -
    Constraints-cyberbrick-Alpine-board.md
parent_task_id: TASK-22
priority: medium
ordinal: 55000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
End-to-end validation on a physical Raspberry Pi Zero 2 W installed from the cyberbrick runbook, paired with unit's watch-layer MCU firmware. AWS deploy/registration, SD-card installation, and on-device commands are executed by the user; the agent prepares commands and verifies evidence. Video acceptance follows the expectation documented by the toolchain spike — if streaming is blocked at the kernel level, the degraded state is documented and a follow-up task is filed.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A cyberbrick board installed per the runbook registers through the standard AWS flow, is born under a raspi rig, and converges the full REDCON ladder from office with correct command feedback and lifecycle projections.
- [ ] #2 Motor control and MCP behavior match unit on the same hardware.
- [ ] #3 Video behavior matches the expectation documented by the toolchain spike, with any degraded state recorded and a follow-up task filed.
- [ ] #4 The board survives read-only-root reboots with OpenRC starting all daemons offline, matching unit's verified reboot behavior.
<!-- AC:END -->
