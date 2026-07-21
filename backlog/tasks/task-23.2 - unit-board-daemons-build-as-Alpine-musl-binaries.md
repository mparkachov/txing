---
id: TASK-23.2
title: unit board daemons build as Alpine musl binaries
status: To Do
assignee: []
created_date: '2026-07-21 09:01'
labels: []
milestone: m-4
dependencies:
  - TASK-23.1
references:
  - devices/unit/daemon/justfile
  - devices/unit/board/kvs_master/CMakeLists.txt
  - devices/cyberbrick/daemon/justfile
documentation:
  - >-
    backlog/docs/architecture/board-musl-static-builds/doc-30 -
    Board-musl-static-builds-architecture.md
  - >-
    backlog/docs/constraints/board-musl-static-builds/doc-32 -
    Constraints-board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 58000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace unit's Debian build paths with Alpine recipes mirroring cyberbrick's _alpine-build: the unit daemon justfile no longer uses debian:trixie or the Raspberry Pi apt repository; the Go daemon stays CGO_ENABLED=0 static, the hardware worker becomes fully static musl, and the KVS master builds musl-dynamic against stock Alpine libcamera. Unit's KVS master CMake adopts the protobuf CONFIG discovery cyberbrick uses — a patch serving unit's own Alpine build, consistent with doc-29's scoping rule.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 devices/unit/daemon/justfile builds all three unit board binaries in the pinned alpine:3.23.5 linux/arm64 image; the trixie recipes and the Raspberry Pi apt repository configuration are removed.
- [ ] #2 devices/unit/board/kvs_master/CMakeLists.txt uses find_package(Protobuf CONFIG REQUIRED) as cyberbrick does, with no other Alpine-specific source divergence from cyberbrick introduced.
- [ ] #3 Local builds assert linkage per policy: daemon and hardware worker statically linked with no ELF interpreter; KVS master musl-dynamic resolving the stock Alpine libcamera sonames with no unresolved ldd entries.
<!-- AC:END -->
