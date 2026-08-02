---
id: TASK-23.2
title: unit board daemons build as Alpine musl binaries
status: Done
assignee:
  - '@claude'
created_date: '2026-07-21 09:01'
updated_date: '2026-08-02 12:55'
labels: []
milestone: m-4
dependencies: []
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
modified_files:
  - devices/unit/daemon/justfile
  - devices/unit/board/kvs_master/CMakeLists.txt
  - shared/aws/python/tests/test_versioning.py
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
- [x] #1 devices/unit/daemon/justfile builds all three unit board binaries in the pinned alpine:3.23.5 linux/arm64 image; the trixie recipes and the Raspberry Pi apt repository configuration are removed.
- [x] #2 devices/unit/board/kvs_master/CMakeLists.txt uses find_package(Protobuf CONFIG REQUIRED) as cyberbrick does, with no other Alpine-specific source divergence from cyberbrick introduced.
- [x] #3 Local builds assert linkage per policy: daemon and hardware worker statically linked with no ELF interpreter; KVS master musl-dynamic resolving the stock Alpine libcamera sonames with no unresolved ldd entries.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Read unit daemon justfile (trixie recipes) and cyberbrick daemon justfile (_alpine-build) end to end
2. Patch devices/unit/board/kvs_master/CMakeLists.txt to protobuf CONFIG discovery (mirror cyberbrick)
3. Rewrite unit justfile build recipes onto pinned alpine:3.23.5: daemon CGO_ENABLED=0 static, hardware worker static via source-built gRPC stack per doc-30, KVS master musl-dynamic with stock Alpine libcamera; remove trixie image var, trixie recipes, and raspi apt repo blocks
4. Add linkage assertions per doc-30 recipe (static: no PT_INTERP, accept static-pie; KVS: musl interpreter + libcamera.so.0.6, ldd fully resolved)
5. Run all three builds locally via the new recipes and capture evidence
6. Record notes/modified files, check ACs, close out
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
CMake patch done: devices/unit/board/kvs_master/CMakeLists.txt now uses find_package(Protobuf CONFIG REQUIRED) unconditionally with cyberbrick's comment; normalized diff against cyberbrick's CMakeLists shows only the pre-existing cyberbrick version-override block and a proto-path message string remain — no Alpine-specific divergence (AC #2).

Justfile rewrite done: removed docker_kvs_master_build_image/debian:trixie, kvs-build-trixie, hardware-build-trixie, _cpp-build-trixie (including both raspi apt repo blocks); added alpine_build_image/platform pins (alpine:3.23.5, linux/arm64), static toolchain version pins (absl 20250814.1, protobuf 31.1, re2 2025-11-05, c-ares 1.34.8, grpc 1.76.0), daemon-build-alpine / kvs-build-alpine / hardware-build-alpine wrappers, and _alpine-build with: assert_static (accepts 'statically linked|static-pie linked', hard-fails on PT_INTERP), assert_musl_dynamic (cyberbrick's), ensure_static_toolchain (source-builds the static gRPC stack per doc-30 into a cached prefix at target/alpine-static-toolchain, keyed by a version-spec marker), CGO_ENABLED=0 static daemon build with DaemonVersion injection from release/versions/unit, static hardware worker (-DCMAKE_EXE_LINKER_FLAGS=-static + CMAKE_PREFIX_PATH=/toolchain), musl-dynamic KVS master asserting libcamera.so.0.6/libcamera-base.so.0.6. docker-build now delegates to _alpine-build all and writes cyberbrick-style metadata (buildImage/buildPlatform), keeping version from release/versions/unit. kvs-clean also removes docker-build dir and the toolchain cache.

test_versioning.py: unit justfile assertions flipped from trixie/raspi/libcamera-0.7 to alpine-pin/no-debian/no-raspi/libcamera-0.6/static flags. Suite passes: 21 passed, 8 subtests. Unit workflow assertions (release-unit.yml) intentionally untouched — that flip belongs to TASK-23.4. Full 'just docker-build' (all three binaries) running for AC #1/#3 evidence.

AC #1/#3 evidence from 'just unit::daemon::docker-build' (single alpine:3.23.5 linux/arm64 container, all three binaries):
- txing-unit-daemon: CGO_ENABLED=0, 'statically linked' aarch64 ELF, --version prints 0.15.4 (DaemonVersion injected from release/versions/unit); -buildvcs=false added because git VCS stamping fails on the read-only bind-mounted repo inside the container.
- txing-unit-kvs-master: musl interpreter /lib/ld-musl-aarch64.so.1, ldd fully resolved incl. libcamera.so.0.6 + libcamera-base.so.0.6, ctest 1/1 passed, --version 0.15.4. Built with the protobuf CONFIG patch — no other CMake change needed.
- txing-unit-hardware-worker: 'static-pie linked' (no PT_INTERP), built against the source-built static toolchain (first build exercised the cold path: 'building static toolchain (alpine=3.23.5 absl=20250814.1 protobuf=31.1 re2=2025-11-05 cares=1.34.8 grpc=1.76.0)' into target/alpine-static-toolchain cache), ctest 2/2 passed, --version 0.15.4.
- metadata.json written with buildImage docker.io/library/alpine:3.23.5, buildPlatform linux/arm64, version 0.15.4.
- Cross-distro bonus check: daemon + hardware worker ran --version successfully in a bare debian:trixie container.
- shared/aws python versioning suite green (21 passed, 8 subtests) with the flipped justfile assertions.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Unit board builds migrated from debian:trixie + Raspberry Pi apt repositories to the pinned alpine:3.23.5 toolchain. The justfile's trixie recipes and raspi repo blocks are gone, replaced by cyberbrick-style daemon-build-alpine/kvs-build-alpine/hardware-build-alpine/_alpine-build recipes implementing the m-4 linkage policy: CGO_ENABLED=0 static Go daemon, fully static hardware worker (static gRPC stack source-built per doc-30 into a cached toolchain prefix), musl-dynamic KVS master asserting stock Alpine libcamera 0.6 sonames. The unit KVS master CMake adopts protobuf CONFIG discovery, eliminating the last Alpine-relevant divergence from cyberbrick. All three binaries built, asserted, and version-smoked in one docker-build run; the static pair additionally verified on bare debian:trixie. Versioning tests updated and green. Unblocks TASK-23.4 (release pipeline) and feeds TASK-23.5 (cross-distro smoke).
<!-- SECTION:FINAL_SUMMARY:END -->
