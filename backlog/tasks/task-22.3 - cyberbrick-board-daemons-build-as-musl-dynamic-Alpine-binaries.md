---
id: TASK-22.3
title: cyberbrick board daemons build as musl-dynamic Alpine binaries
status: Done
assignee:
  - '@codex'
created_date: '2026-07-15 07:37'
updated_date: '2026-07-16 06:15'
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
modified_files:
  - justfile
  - devices/cyberbrick/justfile
  - devices/cyberbrick/daemon
  - devices/cyberbrick/board
  - devices/cyberbrick/proto
  - devices/cyberbrick/docs
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
- [x] #1 devices/cyberbrick carries the complete board stack with cyberbrick naming end-to-end and no residual unit identifiers in code, config, protos, or generated stubs.
- [x] #2 All three daemons build via just recipes in the pinned Alpine aarch64 container, dynamically linked against musl, with build-time assertions on the musl interpreter, fully resolved shared libraries, and the expected libcamera linkage.
- [x] #3 Host-side Go tests and C++ unit tests for the copied stack pass, and existing unit builds and tests are unchanged.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Copy only the tracked unit board stack into devices/cyberbrick: daemon sources/tests/module files, board workers and local guidance/docs, the two private proto contracts, and the board-video documentation; do not copy devices/unit/mcu or any ignored build/cache output.
2. Rename device-owned identifiers end-to-end in the copied sources: Go module/imports/command/version symbol, binaries, config and socket paths, adapter ID, CMake targets/namespaces, and proto packages/services/paths. Regenerate the cyberbrick Go protobuf and gRPC stubs from the renamed proto sources with the pinned generator versions rather than editing generated files.
3. Add cyberbrick just routing plus pinned docker.io/library/alpine:3.23.5 linux/arm64 recipes for the Go daemon, KVS master, hardware worker, and aggregate docker build. Keep source mounted read-only, build in container scratch space, use the proven apk dependency sets and KVS protobuf CONFIG-mode adjustment, and assert aarch64 ELF, /lib/ld-musl-aarch64.so.1, complete ldd resolution, and libcamera.so.0.6/libcamera-base.so.0.6 for KVS.
4. Run host Go tests and both copied C++ unit-test suites, then run all three Alpine builds through the aggregate just recipe on the native arm64 Docker daemon and inspect their emitted binaries/metadata. Re-run the corresponding existing unit Go/C++ tests and compare the unit tree against the pre-change baseline to prove it was untouched.
5. Audit the cyberbrick tree for complete tracked-file parity and residual unit identifiers, run justfile/POSIX and diff checks, record results in TASK-22.3, and mark Done only after all three acceptance criteria are evidenced. No AWS, firmware, release, OpenRC provisioning, or board action is run.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementation completed:

- Copied the complete tracked unit board software surface into devices/cyberbrick: the Go daemon/module/tests, KVS master, hardware worker, local board guidance/README, both private proto contracts, generated Go protobuf/gRPC stubs, daemon env template, and board-video documentation. No MCU directory or ignored build/cache content was copied.
- Renamed ownership end-to-end: txing-cyberbrick-* binaries, github.com/mparkachov/txing/devices/cyberbrick/daemon module/imports, dev.txing.cyberbrick.Daemon adapter, /root/.config/txing/cyberbrick-daemon config subdir, cyberbrick daemon/hardware sockets, CMake targets and C++ namespaces, txing.cyberbrick.* proto packages, and CyberbrickHardware service. Go stubs were regenerated with protoc-gen-go v1.36.10 and protoc-gen-go-grpc v1.5.1.
- Added root/device just routing and daemon-build-alpine, kvs-build-alpine, hardware-build-alpine, plus aggregate docker-build. All use docker.io/library/alpine:3.23.5 on native linux/arm64, a read-only repository mount, the proven apk package union, CGO external linking for Go, and KVS protobuf CONFIG discovery. Each binary is rejected unless file/readelf/ldd prove aarch64, /lib/ld-musl-aarch64.so.1, and no unresolved libraries; KVS additionally requires libcamera.so.0.6 and libcamera-base.so.0.6.

Validation evidence:

- Copied host suite: Go test ./... passed; KVS CTest 1/1 passed; hardware-worker CTest 1/1 passed.
- Aggregate Alpine build passed in alpine:3.23.5 arm64 (resolved digest sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40). Container Go tests passed; KVS CTest 1/1 passed; hardware-worker CTest 2/2 passed.
- All three persisted outputs are ARM aarch64 dynamically linked ELFs with interpreter /lib/ld-musl-aarch64.so.1. Build-time ldd checks found no missing libraries. KVS resolved libcamera.so.0.6 and libcamera-base.so.0.6. Metadata records Alpine 3.23.5, linux/arm64, version 0.15.4, and all three output paths.
- Existing unit suite rerun unchanged: Go test ./... passed; KVS CTest 1/1 passed; hardware-worker CTest 1/1 passed. git diff for devices/unit is empty.
- Normalizing Cyberbrick ownership names back to unit produces exact runtime/source/config/test/proto parity. The only remaining source difference is the approved KVS protobuf CONFIG-mode discovery. Tracked-copy parity, generated-stub provenance, prohibited runtime identifier grep, just/POSIX syntax, root routing, and git diff whitespace checks passed.

No AWS, firmware, release publication, OpenRC host configuration, or physical-board command was run.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added a complete Cyberbrick-owned copy of the unit board stack without copying the MCU or modifying unit sources. The Go daemon, KVS master, hardware worker, private proto packages/services, generated Go stubs, config/socket paths, adapter identity, local docs, and just routing now use Cyberbrick identifiers end-to-end. Added reproducible Alpine 3.23.5 native-arm64 builds with musl interpreter, resolved-library, and libcamera 0.6 assertions. Copied host tests, full container builds/tests, persisted ELF audits, unchanged-unit tests, source-parity comparison, identifier checks, and shell/diff validation all pass. No deployment or device operation was performed.
<!-- SECTION:FINAL_SUMMARY:END -->
