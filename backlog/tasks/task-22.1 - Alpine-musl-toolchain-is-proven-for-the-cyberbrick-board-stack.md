---
id: TASK-22.1
title: Alpine musl toolchain is proven for the cyberbrick board stack
status: To Do
assignee: []
created_date: '2026-07-15 07:36'
labels: []
milestone: m-3
dependencies: []
references:
  - devices/unit/daemon/justfile
  - devices/unit/board/kvs_master
  - devices/unit/board/hardware_worker
documentation:
  - >-
    backlog/docs/architecture/cyberbrick-device-type/doc-27 -
    Cyberbrick-device-type-architecture.md
  - >-
    backlog/docs/constraints/cyberbrick-alpine-board/doc-29 -
    Constraints-cyberbrick-Alpine-board.md
parent_task_id: TASK-22
priority: high
ordinal: 50000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
De-risking spike: prove that unit's three board daemons (Go daemon, KVS master, hardware worker) can be built in a pinned Alpine aarch64 container dynamically linked against musl, before any code is copied. Establish the facts the later build tasks and runbook depend on: pinned Alpine version, apk package set (usrsctp, log4cplus, libcamera availability), the apk libcamera soname for ldd assertions, required source patches for musl/upstream-libcamera compatibility, and the kernel-level video feasibility on Alpine's Raspberry Pi kernel (CSI/ISP pipeline, bcm2835-codec H.264 encoder, pwm-2chan overlay availability). No repository changes; findings are recorded as task notes and folded into the architecture doc.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Both C++ board workers and the Go daemon build from unit sources in a pinned Alpine aarch64 container, dynamically linked against musl, with the musl interpreter present and all shared libraries resolved.
- [ ] #2 Video feasibility on Alpine's Raspberry Pi kernel (camera pipeline, H.264 encoder, PWM overlay) is documented with an explicit expectation for on-device video in this phase.
- [ ] #3 The pinned Alpine version, apk package set, libcamera soname, and any required source patches are recorded for reuse by the build, release, and runbook tasks.
<!-- AC:END -->
