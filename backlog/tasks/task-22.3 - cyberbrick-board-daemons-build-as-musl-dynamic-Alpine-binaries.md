---
id: TASK-22.3
title: cyberbrick board daemons build as musl-dynamic Alpine binaries
status: To Do
assignee: []
created_date: '2026-07-15 07:37'
labels: []
milestone: m-3
dependencies:
  - TASK-22.1
references:
  - devices/unit/daemon
  - devices/unit/board
  - devices/unit/proto
documentation:
  - >-
    backlog/docs/architecture/cyberbrick-device-type/doc-27 -
    Cyberbrick-device-type-architecture.md
  - >-
    backlog/docs/constraints/cyberbrick-alpine-board/doc-29 -
    Constraints-cyberbrick-Alpine-board.md
parent_task_id: TASK-22
priority: high
ordinal: 52000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The full unit board stack (Go daemon, KVS master, hardware worker, protos, env template, board docs) exists under devices/cyberbrick with cyberbrick-owned identifiers end-to-end (binaries, sockets, config dirs, adapter IDs, proto packages txing.cyberbrick.*, regenerated stubs) and builds reproducibly in the pinned Alpine aarch64 container from the toolchain spike, dynamically linked against musl. The MCU directory is not copied. Existing unit sources, builds, and tests are untouched.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 devices/cyberbrick carries the complete board stack with cyberbrick naming end-to-end and no residual unit identifiers in code, config, protos, or generated stubs.
- [ ] #2 All three daemons build via just recipes in the pinned Alpine aarch64 container, dynamically linked against musl, with build-time assertions on the musl interpreter, fully resolved shared libraries, and the expected libcamera linkage.
- [ ] #3 Host-side Go tests and C++ unit tests for the copied stack pass, and existing unit builds and tests are unchanged.
<!-- AC:END -->
