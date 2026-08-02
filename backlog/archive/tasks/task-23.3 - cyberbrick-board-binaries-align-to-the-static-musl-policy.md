---
id: TASK-23.3
title: cyberbrick board binaries align to the static-musl policy
status: Done
assignee: []
created_date: '2026-07-21 09:01'
updated_date: '2026-08-02 12:55'
labels: []
milestone: m-4
dependencies: []
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
- [x] #1 The cyberbrick Go daemon builds CGO_ENABLED=0 static and the hardware worker builds fully static in both devices/cyberbrick/daemon/justfile and release-cyberbrick.yml; the KVS master build is unchanged.
- [x] #2 The musl assert script (or its shared successor) enforces static linkage for the daemon and hardware worker and musl-dynamic plus stock Alpine libcamera sonames for the KVS master.
- [x] #3 doc-29's ABI and toolchain section is amended to defer to doc-32, and the cyberbrick workflow-text assertions in shared/aws/python/tests/test_versioning.py are updated and pass.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extract the static protobuf/gRPC toolchain build into release/scripts/build-board-static-toolchain.sh (pins + cache marker as single source of truth); refactor the unit justfile heredoc to call it.
2. devices/cyberbrick/daemon/justfile: daemon builds GOOS=linux GOARCH=arm64 CGO_ENABLED=0 static (drops -linkmode=external, adds -buildvcs=false); hardware worker builds fully static against the cached /toolchain prefix; KVS master untouched; clean removes the toolchain cache.
3. release-cyberbrick.yml: same linkage flip; hardware-worker job builds the static toolchain via the shared script; apk set gains curl, openssl-libs-static, zlib-static.
4. assert-cyberbrick-musl.sh becomes kind-based: daemon/hardware-worker assert static (statically linked|static-pie linked, no PT_INTERP), kvs-master asserts musl-dynamic + libcamera 0.6 sonames.
5. Amend doc-29 ABI section to defer to doc-32; flip cyberbrick assertions in test_versioning.py.
6. Verify: versioning suite green; just cyberbrick::daemon::docker-build end-to-end; static pair executes on bare debian:trixie.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Extracted the static protobuf/gRPC toolchain build into release/scripts/build-board-static-toolchain.sh (pins absl 20250814.1 / protobuf 31.1 / re2 2025-11-05 / c-ares 1.34.8 / grpc 1.76.0 + Alpine-keyed cache marker as single source of truth); the unit justfile heredoc now calls it instead of carrying an inline copy.

devices/cyberbrick/daemon/justfile: daemon builds GOOS=linux GOARCH=arm64 CGO_ENABLED=0 static with -buildvcs=false (drops -linkmode=external); hardware worker builds fully static against the cached /toolchain prefix (-DCMAKE_PREFIX_PATH=/toolchain -DCMAKE_EXE_LINKER_FLAGS=-static -DOPENSSL_USE_STATIC_LIBS=TRUE -DZLIB_USE_STATIC_LIBS=ON); new assert_static (statically linked|static-pie linked, no PT_INTERP); apk set gains curl/openssl-libs-static/zlib-static; kvs-master build untouched; clean removes the toolchain cache. release-cyberbrick.yml got the same linkage flip, with the hardware-worker matrix job building the toolchain via the shared script into RUNNER_TEMP.

release/scripts/assert-cyberbrick-musl.sh is now kind-based: daemon/hardware-worker assert static linkage, kvs-master asserts musl-dynamic + libcamera.so.0.6/libcamera-base.so.0.6. doc-29 ABI section amended to defer to doc-32 (musl-dynamic-only rule superseded; static pair depends only on the kernel).

Evidence: just cyberbrick::daemon::docker-build green end-to-end on alpine:3.23.5 — daemon statically linked (go tests ok), kvs-master musl interpreter + libcamera 0.6 + ctest 1/1, hardware worker static-pie linked + ctest 2/2 reusing the cached toolchain via the shared script; daemon + hardware worker ran --version 0.15.4 on bare debian:trixie; assert script passed all three kinds in a stock-Alpine runtime container and rejected mismatched kinds in negative tests; just unit::daemon::hardware-build-alpine re-verified the refactored unit path (static-pie, ctest 2/2); test_versioning.py: 21 passed, 8 subtests.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Cyberbrick daemon and hardware worker now build fully static musl (CGO_ENABLED=0 / static gRPC stack via new shared release/scripts/build-board-static-toolchain.sh) in both the justfile and release-cyberbrick.yml; kvs-master stays musl-dynamic against Alpine libcamera 0.6. assert-cyberbrick-musl.sh enforces linkage per kind, doc-29 defers to doc-32, and the flipped test assertions pass. Verified by a full local Alpine docker-build, debian:trixie execution smoke of the static pair, and assert-script positive/negative runs.
<!-- SECTION:FINAL_SUMMARY:END -->
