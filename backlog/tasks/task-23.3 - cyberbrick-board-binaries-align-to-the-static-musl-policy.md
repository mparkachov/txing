---
id: TASK-23.3
title: cyberbrick board binaries align to the static-musl policy
status: To Do
assignee: []
created_date: '2026-07-21 09:01'
labels: []
milestone: m-4
dependencies:
  - TASK-23.1
references:
  - devices/cyberbrick/daemon/justfile
  - .github/workflows/release-cyberbrick.yml
  - release/scripts/assert-cyberbrick-musl.sh
  - shared/aws/python/tests/test_versioning.py
documentation:
  - >-
    backlog/docs/constraints/board-musl-static-builds/doc-32 -
    Constraints-board-musl-static-builds.md
  - >-
    backlog/docs/constraints/cyberbrick-alpine-board/doc-29 -
    Constraints-cyberbrick-Alpine-board.md
parent_task_id: TASK-23
priority: medium
ordinal: 59000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Align cyberbrick's build to the milestone's static-where-possible policy: the Go daemon drops -linkmode=external and builds CGO_ENABLED=0 static, the hardware worker links fully static, and the KVS master stays musl-dynamic against stock Alpine libcamera. doc-29's ABI section — which required every shipped cyberbrick binary to be musl-dynamic — is amended to defer to doc-32.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The cyberbrick Go daemon builds CGO_ENABLED=0 static and the hardware worker builds fully static in both devices/cyberbrick/daemon/justfile and release-cyberbrick.yml; the KVS master build is unchanged.
- [ ] #2 The musl assert script (or its shared successor) enforces static linkage for the daemon and hardware worker and musl-dynamic plus stock Alpine libcamera sonames for the KVS master.
- [ ] #3 doc-29's ABI and toolchain section is amended to defer to doc-32, and the cyberbrick workflow-text assertions in shared/aws/python/tests/test_versioning.py are updated and pass.
<!-- AC:END -->
