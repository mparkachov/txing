---
id: TASK-22.5
title: cyberbrick Alpine board runbook is complete
status: To Do
assignee: []
created_date: '2026-07-15 07:38'
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
- [ ] #1 A cyberbrick board runbook documents the manual fresh install end-to-end on Alpine (sys install, networking/chronyd, mise, cert bundle, OpenRC services, PWM overlay, read-only root) at parity of coverage with the unit board runbook.
- [ ] #2 The maintenance section documents the writable-root update window including the constraint that apk and mise upgrades happen together and Alpine release bumps require a matching cyberbrick release.
- [ ] #3 Installation and artifacts docs index cyberbrick (assets, on-device layout, init scripts, ldd policy), and documentation-consistency tests pass with existing unit assertions unchanged.
<!-- AC:END -->
