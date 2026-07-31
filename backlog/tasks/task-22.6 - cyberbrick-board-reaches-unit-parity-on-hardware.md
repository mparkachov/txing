---
id: TASK-22.6
title: cyberbrick board reaches unit parity on hardware
status: Done
assignee: []
created_date: '2026-07-15 07:38'
updated_date: '2026-07-31 20:48'
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
- [x] #1 A cyberbrick board installed per the runbook registers through the standard AWS flow, is born under a raspi rig, and converges the full REDCON ladder from office with correct command feedback and lifecycle projections.
- [x] #2 Motor control and MCP behavior match unit on the same hardware.
- [x] #3 Video behavior matches the expectation documented by the toolchain spike, with any degraded state recorded and a follow-up task filed.
- [x] #4 The board survives read-only-root reboots with OpenRC starting all daemons offline, matching unit's verified reboot behavior.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Closed on 2026-07-31 by operator decision, on the basis of the shared
implementation rather than a separate cyberbrick hardware run.

The consolidation in TASK-23.8 and TASK-23.9 means one implementation serves both
device types: the daemon, KVS master and hardware worker are built once from
devices/common/board/, with the device type injected at build time to select
binary names, the hardware socket path and the release stream, and all three speak
the device-independent txing.board.* gRPC packages. The cyberbrick branch this was
built on is the branch that carries that common board code.

TASK-23.13 drove a unit board from a blank card to REDCON 1 with live video and
working motion control, exercising that shared path end to end on Alpine with a
read-only root and a cold boot. The operator accepts that as covering the
cyberbrick ACs here, since what differs between the two device types is build-time
configuration rather than the code under test.

Recorded plainly for anyone reading later: the evidence for the criteria below is
inferential for cyberbrick specifically. The full REDCON ladder (AC1), motor and
MCP parity against unit on cyberbrick hardware (AC2), and read-only-root reboot
survival on a cyberbrick board (AC4) were not separately driven in this pass.
Earlier cyberbrick hardware work is recorded in TASK-22.5 and TASK-23.7.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Cyberbrick hardware parity accepted on the strength of the shared board
implementation and the unit validation in TASK-23.13.

After the TASK-23.8 and TASK-23.9 consolidation the two device types run one
implementation, built once from devices/common/board/ with the device type
injected at build time and speaking device-independent txing.board.* protocol
packages. A unit board was taken from a blank card to REDCON 1 with live video and
working motion control under a read-only root across a cold boot, exercising that
path end to end.

The cyberbrick-specific criteria here were not separately driven in this pass; the
implementation notes state which ones are covered inferentially so the distinction
is not lost.
<!-- SECTION:FINAL_SUMMARY:END -->
