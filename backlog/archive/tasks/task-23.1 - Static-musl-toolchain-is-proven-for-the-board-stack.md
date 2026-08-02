---
id: TASK-23.1
title: Static musl toolchain is proven for the board stack
status: Done
assignee:
  - '@claude'
created_date: '2026-07-21 09:01'
updated_date: '2026-07-21 09:42'
labels: []
milestone: m-4
dependencies: []
references:
  - devices/cyberbrick/daemon/justfile
  - devices/unit/board/hardware_worker/CMakeLists.txt
  - .github/workflows/release-cyberbrick.yml
documentation:
  - >-
    backlog/docs/architecture/board-musl-static-builds/doc-30 -
    Board-musl-static-builds-architecture.md
  - >-
    backlog/docs/constraints/board-musl-static-builds/doc-32 -
    Constraints-board-musl-static-builds.md
parent_task_id: TASK-23
priority: high
ordinal: 57000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
De-risking spike mirroring TASK-22.1: prove on the pinned alpine:3.23.5 (linux/arm64) image that the board stack links statically where the policy requires, and that the resulting binaries execute on both Debian and Alpine userlands. No product code changes; durable findings are recorded in the architecture doc.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A fully static musl hardware worker builds on the pinned alpine:3.23.5 linux/arm64 image, using static protobuf/gRPC from apk or a documented ExternalProject-style static source build fallback, and file/readelf show a statically linked aarch64 ELF with no INTERP program header.
- [x] #2 A CGO_ENABLED=0 static Go board daemon builds on the same image, confirming no -linkmode=external requirement remains.
- [x] #3 The static daemon and hardware worker execute successfully (version or startup smoke) in both debian:trixie and alpine:3.23.5 linux/arm64 containers, and the musl-dynamic KVS master build is confirmed unaffected by the policy change.
- [x] #4 The proven apk package set, CMake/link flags, any required source patches, the observed image digest, and the file/readelf/ldd assertion recipe are recorded in the reserved section of doc-30.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect hardware worker CMake and cyberbrick Alpine build recipe for the exact link surface
2. Probe Alpine 3.23.5 apk for static protobuf/gRPC (and their absl/cares/re2/ssl/zlib deps) archives
3. Build a fully static musl hardware worker in the pinned alpine:3.23.5 linux/arm64 container with no product-code changes (external CMake/link flags; ExternalProject-style static source build fallback only if apk lacks static archives)
4. Build the CGO_ENABLED=0 static Go board daemon on the same image without -linkmode=external
5. Smoke-run both static binaries in debian:trixie and alpine:3.23.5 containers; capture file/readelf/ldd evidence and confirm the KVS master build inputs are untouched
6. Record the proven apk set, flags, digest, and assertion recipe in doc-30's reserved section; check ACs and close out
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Probe: alpine:3.23.5 apk ships no static archives for the gRPC stack — grpc-dev/protobuf-dev install only libcares.a and libupb.a, and v3.23 main/community has no grpc/protobuf/abseil *-static packages (relevant static packages that DO exist: zlib-static, openssl-libs-static, pcre2-static; c-ares-dev ships libcares.a). AC #1 therefore takes the documented source-build fallback: abseil 20250814.1, protobuf v31.1, re2 2025-11-05, c-ares v1.34.8, grpc v1.76.0 (tags pinned to the apk package versions) built static-only into an isolated prefix; the hardware worker then builds from unmodified sources with only external flags (-DCMAKE_PREFIX_PATH, -DCMAKE_EXE_LINKER_FLAGS=-static).

Toolchain finding: Alpine gcc defaults to PIE, so plain -static produces a static-PIE (file: 'static-pie linked', ET_DYN, no INTERP header) — still fully static and kernel-only. Assertions must accept 'statically linked|static-pie linked'; the hard invariant is the absence of a PT_INTERP program header. -static -no-pie yields the classic ET_EXEC 'statically linked' if determinism is preferred.

AC #2 evidence: on alpine:3.23.5 (apk go 1.25.x), CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath succeeds for both txing-unit-daemon and txing-cyberbrick-daemon with no -linkmode=external; file reports 'statically linked' aarch64 ELF, readelf shows no INTERP, and --version prints 0.15.4 for both.

AC #1 evidence: fully static hardware worker built on alpine:3.23.5 (observed digest sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40, same as doc-27's pin) from unmodified sources with only -DCMAKE_PREFIX_PATH and -DCMAKE_EXE_LINKER_FLAGS=-static (+OPENSSL_USE_STATIC_LIBS/ZLIB_USE_STATIC_LIBS): file reports 'static-pie linked' ARM aarch64, readelf shows no PT_INTERP, --version prints txing-unit-hardware-worker 0.15.4. Static stack source-built in ~35 min on 8 cores: abseil 20250814.1, protobuf v31.1, re2 2025-11-05, c-ares v1.34.8, grpc v1.76.0 (proto submodules xds/envoy-api/googleapis/opencensus-proto/protoc-gen-validate; all providers=package; openssl/zlib static from apk).

AC #3 evidence: all three binaries (txing-unit-hardware-worker, txing-unit-daemon, txing-cyberbrick-daemon) executed --version successfully in bare debian:trixie and alpine:3.23.5 linux/arm64 containers with zero packages installed. KVS master unaffected: git status shows no spike modifications under devices/ (only the pre-existing cyberbrick board README edit from earlier branch work); the static stack lives in an isolated prefix selected by external flags only.

AC #4: proven contract recorded in doc-30 section 'Proven static toolchain contract (TASK-23.1)' — apk package set, source tags, CMake/link flags, digest, static-PIE finding, and the file/readelf/cross-distro assertion recipe. Spike scripts preserved in the session scratchpad (spike-23-1/01-static-hardware-worker.sh, 02-static-go-daemons.sh, 03-cross-distro-smoke.sh).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Static musl toolchain proven for the board stack on pinned alpine:3.23.5 (linux/arm64). Alpine apk ships no static grpc/protobuf/abseil archives, so the contract is the documented fallback: static-only source builds pinned to apk versions (abseil 20250814.1, protobuf v31.1, re2 2025-11-05, c-ares v1.34.8, grpc v1.76.0) into an isolated prefix, with openssl/zlib static from apk. The unmodified hardware worker then links fully static via external CMake flags alone (static-PIE; no PT_INTERP), and both Go daemons build CGO_ENABLED=0 static with no -linkmode=external. All three binaries ran --version in bare debian:trixie and alpine:3.23.5 containers, proving kernel-only dependencies on both distros. KVS master musl-dynamic build untouched. Full contract + assertion recipe recorded in doc-30; unblocks TASK-23.2 and TASK-23.3.
<!-- SECTION:FINAL_SUMMARY:END -->
