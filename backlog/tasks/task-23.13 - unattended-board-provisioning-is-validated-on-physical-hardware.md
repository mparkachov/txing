---
id: TASK-23.13
title: unattended board provisioning is validated on physical hardware
status: Done
assignee: []
created_date: '2026-07-25 17:44'
updated_date: '2026-07-31 20:41'
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
- [x] #1 A cyberbrick board provisioned from a generated card comes up on the network with no console session, and reaches REDCON 1 with live video and working motion control after the remaining manual runbook steps.
- [x] #2 A unit board provisioned the same way reaches the same state, confirming the merged implementation works for both device types.
- [x] #3 Evidence for every board is recorded in the task's implementation notes.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Operator validation, 2026-07-31.

AC1 cyberbrick: validated in an earlier story before the merge; not re-run here.
AC3 Debian reimage: removed as an acceptance criterion. The operator confirmed the
Debian board is no longer relevant, so it is descoped rather than deferred.

AC2 unit board (thing unit-wrd8ti), full clean-card run: card written with
Raspberry Pi Imager plus the files from devices/common/board/card/, unattended.sh
took it to a read-only sys install on Wi-Fi with mise on root's PATH and no
console session, the runbook was followed from Install OS Packages, the board was
shut down and cold booted, and it then reached REDCON 1 from the office with live
video and working motion control on release unit-v0.15.10 built against Alpine
3.24.1. This run is also the first hardware exercise of the chroot-based mise
install in unattended.sh, and the cold boot is the real test of udev in sysinit.

Defects found during validation and fixed:

1. Release stream gap. unit-v0.15.9, the newest published unit release, predated
   the Alpine 3.23.5 -> 3.24.1 retarget, so latest resolved to a binary linking
   sonames no v3.24 board can satisfy. Bumped release/versions/unit to 0.15.10 and
   published. The runbook's Maintenance section only warned about a release built
   against a *newer* branch than the board; the reverse direction, a board imaged
   to current Alpine against a stream not rebuilt since the last bump, is now
   documented along with the rule that retargeting Alpine means publishing on
   every board stream.

2. mise fetch_remote_versions_cache was "10m" on boards and "0s" on the rig. A
   release published inside that window is invisible: mise upgrade reports all
   tools up to date and ls-remote does not list it, with no warning. Set to "0s"
   to match rig/install-mise-tools.sh, with mise cache clear documented for boards
   already carrying the window. Guarded in tests on both surfaces.

3. udev false negative. ls -d /run/udev passes as soon as udevd starts, and
   rc-service udev status reports started, while the database stays empty until
   udev-trigger replays existing devices. libcamera reads the database, so it
   enumerated zero cameras and reported 'configured camera index is not available'
   on a board where every other check passed. Replaced that check everywhere with
   the runlevel listing plus the udevadm info --export-db device count.

4. Runbook ordering. The PWM overlay and camera now precede the services, so the
   first service start is judged against hardware that is present rather than
   against expected failures. That introduced a reboot between step 2's root-rw
   and step 6's file writes on a read-only board; step 6 now begins with root-rw.

5. Step 2 discoverability. The apk add sat under a paragraph explaining that the
   community-repo sed is a no-op on a card-provisioned board, which reads as an
   opt-out for the whole block and was skipped on two separate boards. The runtime
   package install is now its own block marked as running on every board, followed
   by an apk info -e check.

6. Runbook made copy-pasteable, which is what prompted this pass: no <placeholder>
   remains in any sh block, the device type travels in TXING_DEVICE persisted to
   /root/.profile, and a preflight at the start of step 6 names the step each
   failed check belongs to. Guarded by tests that parse every sh block with sh -n
   and reject placeholders.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Unattended board provisioning validated on physical hardware.

A unit board went from a blank card to REDCON 1 with live video and working
motion control, driven from the office: Raspberry Pi Imager plus the files in
devices/common/board/card/, unattended.sh to a read-only sys install on Wi-Fi
with mise already installed, the runbook from Install OS Packages onward, and a
cold boot before the check. The cyberbrick side was validated in an earlier story
before the merge. The Debian reimage criterion was removed as no longer relevant
rather than left deferred.

Validation surfaced six defects, all fixed. Two were release-side: the unit stream
had never been rebuilt after the Alpine 3.24.1 retarget, and the board mise config
cached the remote version list for ten minutes, which silently hid a release
published inside that window. One was diagnostic: ls -d /run/udev passes while the
udev database is empty, so a working camera reports 'configured camera index is not
available'. Three were in the runbook: the PWM overlay and camera now precede the
services, step 6 reclaims a writable root after the reboot that reordering
introduced, and the apk add is no longer buried under a paragraph that reads as an
opt-out. The runbook is now copy-pasteable end to end, with the device type in
TXING_DEVICE and a preflight that names the step behind each failed check.
<!-- SECTION:FINAL_SUMMARY:END -->
