---
id: TASK-22.5
title: cyberbrick Alpine board runbook is complete
status: Done
assignee:
  - '@claude'
created_date: '2026-07-15 07:38'
updated_date: '2026-07-21 07:19'
labels: []
milestone: m-3
dependencies:
  - TASK-22.3
references:
  - docs/components/board.md
  - docs/installation.md
  - docs/artifacts.md
documentation:
  - >-
    backlog/docs/architecture/cyberbrick-device-type/doc-27 -
    Cyberbrick-device-type-architecture.md
  - >-
    backlog/docs/constraints/cyberbrick-alpine-board/doc-29 -
    Constraints-cyberbrick-Alpine-board.md
parent_task_id: TASK-22
priority: medium
ordinal: 54000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
An operator can take a blank SD card to a running cyberbrick board using only repository docs, at the same coverage level as unit's board runbook: Alpine sys install on the Pi Zero 2 W, default networking and time sync, mise-based artifact install, certificate/config placement, OpenRC services, PWM overlay, read-only root configuration, and the maintenance/update workflow including the coupled apk + mise upgrade rule for musl-dynamic binaries. Existing unit documentation stays byte-identical where tests assert it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A cyberbrick board runbook documents the manual fresh install end-to-end on Alpine (sys install, networking/chronyd, mise, cert bundle, OpenRC services, PWM overlay, read-only root) at parity of coverage with the unit board runbook.
- [x] #2 The maintenance section documents the writable-root update window including the constraint that apk and mise upgrades happen together and Alpine release bumps require a matching cyberbrick release.
- [x] #3 Installation and artifacts docs index cyberbrick (assets, on-device layout, init scripts, ldd policy), and documentation-consistency tests pass with existing unit assertions unchanged.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Write docs/components/cyberbrick-board.md, the cyberbrick Alpine board runbook, referencing docs/components/board.md for unit-parity behavior and covering install end-to-end: Alpine v3.23 aarch64 image + setup-alpine + setup-disk -m sys on the Pi Zero 2 W, default ifupdown-ng/wpa_supplicant/udhcpc networking and chronyd, apk runtime package set from the proven build union, root-owned mise with version_prefix cyberbrick-v and the three asset patterns, cert/config placement under /root/.config/txing/cyberbrick-daemon, OpenRC supervise-daemon init scripts for hardware-worker -> daemon -> kvs-master with checkpath runtime dirs, env-file sourcing, and a bounded chronyc waitsync guard, PWM overlay on the boot FAT, read-only-root fstab/tmpfs layout with udhcpc RESOLV_CONF=/run/resolv.conf and root-rw/root-ro aliases, and a final reboot check including musl-interpreter and libcamera 0.6 ldd verification plus the physical smoke-test boundary owned by TASK-22.6.
2. Add a Maintenance section documenting the writable-root window with the coupled apk upgrade + mise upgrade rule for musl-dynamic binaries, ldd verification before reboot, and the rule that Alpine branch/libcamera soname bumps require a matching cyberbrick release built on that Alpine version first (justfile image + workflow containers + device apk branch move together).
3. Index cyberbrick in docs/installation.md (Cyberbrick Board Host section + short production flow), extend the Cyberbrick board section in docs/artifacts.md with the on-device layout, OpenRC init script paths, and the ldd policy, and add the runbook and cyberbrick type catalog row to docs/README.md; link the runbook from devices/cyberbrick/board/README.md.
4. Add a cyberbrick documentation-consistency test to shared/aws/python/tests/test_versioning.py asserting the runbook's Alpine/OpenRC/musl invariants and the installation/artifacts indexing, without modifying any existing unit assertion.
5. Validate: run the shared/aws python test suite via uv, confirm git diff touches no unit documentation, and record results in the task before marking Done.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Wrote docs/components/cyberbrick-board.md covering the full Alpine fresh install at unit-runbook coverage: v3.23 Raspberry Pi image + setup-alpine defaults (ifupdown-ng/wpa_supplicant/udhcpc, chronyd, openssh), sys conversion with setup-disk -m sys /dev/mmcblk0p2, the proven apk runtime package superset from the pinned build container, root-owned mise with cyberbrick-v version_prefix and the three asset patterns, cert bundle placement under /root/.config/txing/cyberbrick-daemon with the role-policy repair recipe, three supervise-daemon OpenRC init scripts (checkpath runtime dirs, daemon.env sourcing for the hardware worker, bounded chronyc waitsync guard, hardware-worker -> daemon -> kvs-master ordering, rc-update enablement), the pwm-2chan overlay on the boot FAT, read-only-root fstab/tmpfs layout (/tmp, /var/tmp, /var/log, /var/lib/chrony) with udhcpc RESOLV_CONF=/run/resolv.conf and root-rw/root-ro aliases, and a final reboot check asserting the musl interpreter and libcamera 0.6 sonames. The physical smoke-test boundary (camera enumeration, /dev/video11, H.264 capture, both PWM channels) is stated as TASK-22.6 scope. Behavior contracts reference docs/components/board.md per the unit-parity doctrine instead of duplicating them.

Maintenance documents the writable-root window with the coupled apk upgrade + mise upgrade rule, ldd verification before reboot (abort the reboot on unresolved libraries or missing libcamera 0.6 sonames), FAT boot-file sync after kernel upgrades, and the coordinated Alpine bump rule: justfile build image + release workflow containers + device apk branch move together and require a matching cyberbrick release built on that Alpine version first.

Indexed cyberbrick in docs/installation.md (Cyberbrick Board Host section with the short production flow), extended the Cyberbrick board section of docs/artifacts.md with the root-owned on-device layout, the three /etc/init.d init scripts, the no-target rc-update model, and the musl/libcamera ldd policy, added the runbook and the cyberbrick type catalog row to docs/README.md, and linked the runbook from devices/cyberbrick/board/README.md.

Added test_cyberbrick_board_docs_describe_alpine_openrc_runbook to shared/aws/python/tests/test_versioning.py asserting the runbook invariants (sys install, mise config, OpenRC scripts, sockets, PWM overlay, musl/libcamera policy, coupled upgrade wording) and the installation/artifacts/README indexing; the test file diff is 163 lines added, 0 removed, so every existing unit assertion is unchanged. Validation: test_versioning.py 21 passed; full shared/aws python suite 143 passed (fresh linux-aarch64 uv venv; the committed .venv targets another platform). git diff shows docs/components/board.md byte-identical; the single replaced line in docs/artifacts.md is inside the cyberbrick paragraph. No AWS, release, or board operations were run.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Cyberbrick now has a complete Alpine board runbook at docs/components/cyberbrick-board.md, giving an operator the blank-SD-to-running-board path at unit-runbook coverage: Alpine v3.23 sys install on the Pi Zero 2 W, stock networking and chronyd, root-owned mise install from the cyberbrick-v* stream, cert/config placement, three supervise-daemon OpenRC services with correct ordering and offline starts, the PWM overlay, and the read-only-root layout. Maintenance codifies the musl-dynamic coupling: apk and mise upgrades share one writable-root window with ldd verification before reboot, and Alpine release bumps require a matching cyberbrick release built on that Alpine version first. Installation, artifacts, and docs-index pages now index cyberbrick (assets, on-device layout, init scripts, ldd policy), and a new documentation-consistency test locks the runbook and indexing invariants while leaving every existing unit assertion untouched (full shared/aws suite: 143 passed). Physical-board validation remains TASK-22.6.
<!-- SECTION:FINAL_SUMMARY:END -->
