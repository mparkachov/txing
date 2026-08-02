---
id: TASK-22.1
title: Alpine musl toolchain is proven for the cyberbrick board stack
status: Done
assignee:
  - '@codex'
created_date: '2026-07-15 07:36'
updated_date: '2026-07-15 20:06'
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
- [x] #1 Both C++ board workers and the Go daemon build from unit sources in a pinned Alpine aarch64 container, dynamically linked against musl, with the musl interpreter present and all shared libraries resolved.
- [x] #2 Video feasibility on Alpine's Raspberry Pi kernel (camera pipeline, H.264 encoder, PWM overlay) is documented with an explicit expectation for on-device video in this phase.
- [x] #3 The pinned Alpine version, apk package set, libcamera soname, and any required source patches are recorded for reuse by the build, release, and runbook tasks.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Reproduce the unit Go daemon, hardware-worker, and KVS-master builds from a read-only repository mount in a pinned Alpine aarch64 container, iterating only in disposable scratch space to identify the exact apk package set and any source patches required.
2. Inspect each resulting ELF with readelf and ldd to prove the musl interpreter, dynamic linkage, complete shared-library resolution, and the exact upstream libcamera soname.
3. Establish Raspberry Pi Zero 2 W kernel feasibility from authoritative Alpine/kernel package evidence for the CSI/ISP pipeline, bcm2835-codec H.264 encoder, and pwm-2chan overlay; state the phase-one on-device video expectation explicitly.
4. Record reproducible commands, package/version facts, patch findings, limitations, and validation evidence in TASK-22.1 notes; fold durable conclusions into architecture doc-27 using the Backlog CLI.
5. Check all acceptance criteria, add a PR-quality final summary, and mark TASK-22.1 Done only if every proof is complete. No product source, firmware, infrastructure, or configuration files will be changed.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
## Toolchain spike evidence (2026-07-15)

### Pin and build environment

- Pin the build image to `docker.io/library/alpine:3.23.5` on `linux/arm64`. The proven image resolved to `alpine@sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40`, reported `aarch64`, and contained Alpine `3.23.5`. The on-device apk repositories must stay on the matching `v3.23` branch.
- Build/test host: native arm64 Docker daemon. The repository was bind-mounted read-only; all copied sources, build trees, Go caches, downloads, and patches were created only inside disposable container filesystems.
- The pinned AWS KVS WebRTC SDK commit remained `bb106510cf74edd2c24881c1ae94ceaa0083d15c`.

### Top-level apk package set

Use this union in the Alpine build image:

```text
build-base cmake pkgconf git perl ca-certificates
curl-dev openssl-dev log4cplus-dev libsrtp-dev libusrsctp-dev
libwebsockets-dev zlib-dev libcamera-dev linux-headers
protobuf-dev protobuf grpc-dev grpc-plugins
go binutils file
```

Component subsets:

- Go daemon: `go build-base ca-certificates binutils file`.
- Hardware worker: `build-base cmake pkgconf protobuf-dev protobuf grpc-dev grpc-plugins binutils file ca-certificates`.
- KVS master: the hardware-worker C++ set plus `git perl curl-dev openssl-dev log4cplus-dev libsrtp-dev libusrsctp-dev libwebsockets-dev zlib-dev libcamera-dev linux-headers`.

Important Alpine package names are `libusrsctp-dev` (not `usrsctp-dev`), `libsrtp-dev`, and `grpc-plugins` for `grpc_cpp_plugin`. Both previously uncertain dependencies are present in Alpine 3.23 community: `libusrsctp-dev` and `log4cplus-dev`.

Observed package revisions in the proven image/repositories were: build-base 0.5-r3, cmake 4.1.3-r0, pkgconf 2.5.1-r0, git 2.52.0-r0, perl 5.42.2-r0, ca-certificates 20260611-r0, curl-dev 8.20.0-r0, openssl-dev 3.5.7-r0, log4cplus-dev 2.1.2-r0, libsrtp-dev 2.7.0-r0, libusrsctp-dev 0.9.5.0-r1, libwebsockets-dev 4.3.5-r2, zlib-dev 1.3.2-r0, libcamera-dev 0.6.0-r0, protobuf/protobuf-dev 31.1-r1, grpc-dev/grpc-plugins 1.76.0-r2, Go 1.25.10-r0, binutils 2.45.1-r0, file 5.46-r2, and linux-headers 6.16.12-r0. Package revisions may advance within v3.23; the Alpine release branch and built binary ldd assertions are the compatibility boundary.

### Required build adjustments

Exactly one source-level adjustment was required in the disposable cyberbrick-equivalent copy:

- In the KVS master CMake configuration, resolve protobuf in CONFIG mode on Alpine: change the non-Apple `find_package(Protobuf REQUIRED)` call to `find_package(Protobuf CONFIG REQUIRED)`. Alpine gRPC 1.76 imports protobuf's config export; preloading CMake's module-mode protobuf creates a partially duplicated target export and configuration fails. The hardware worker already tries CONFIG mode first and needs no patch.

No musl patch was required in the Go daemon, hardware worker, KVS worker sources, or pinned AWS KVS WebRTC SDK. The existing libcamera capture source compiled unchanged against upstream libcamera 0.6. The KVS SDK emitted only non-fatal upstream deprecation/format warnings.

The Go source does not import C, so `CGO_ENABLED=1` alone is insufficient to force dynamic linkage. Build with external linking, for example:

```sh
CGO_ENABLED=1 GOOS=linux GOARCH=arm64 go build -trimpath \
  -ldflags="-linkmode=external -s -w -X github.com/mparkachov/txing/devices/unit/daemon/internal/daemon.DaemonVersion=<version>" \
  -o txing-cyberbrick-daemon ./cmd/txing-cyberbrick-daemon
```

### Build and ELF proof

All builds used Alpine 3.23.5 aarch64 and completed from unit sources:

- Go daemon: `go test ./...` passed; external-link build succeeded.
- Hardware worker: release build with gRPC and `BUILD_TESTING=ON` succeeded; both CTest cases passed.
- KVS master: release build with gRPC, real pinned KVS SDK, upstream libcamera, and `BUILD_TESTING=ON` succeeded after the protobuf CONFIG-mode adjustment; its CTest passed.

For all three executables, `file` reported ARM aarch64 ELF, `readelf -l` reported `[Requesting program interpreter: /lib/ld-musl-aarch64.so.1]`, and `ldd` contained no `not found` entries. The Go daemon dynamically resolved musl libc. The hardware worker resolved Alpine gRPC/protobuf and their transitive libraries. The KVS master resolved, among others:

```text
libcamera.so.0.6
libcamera-base.so.0.6
libwebsockets.so.19
libsrtp2.so.1
libusrsctp.so.2
libssl.so.3
libcrypto.so.3
libgrpc++.so.1.76
libprotobuf.so.31
libc.musl-aarch64.so.1
```

Therefore the release ldd assertions for Alpine 3.23 must check `libcamera.so.0.6` and `libcamera-base.so.0.6`, in addition to the musl interpreter and the absence of unresolved libraries.

### Raspberry Pi kernel/video feasibility

Direct inspection of Alpine 3.23 packages found:

- `linux-rpi-6.12.85-r0` includes `bcm2835-unicam.ko.xz` (CSI capture), `bcm2835-isp.ko.xz` (VC4 ISP), `bcm2835-codec.ko.xz` (V4L2/MMAL codec), plus Pi 5 `pisp-be` and `rp1-cfe` modules.
- Its kernel config enables `CONFIG_VIDEO_BCM2835_UNICAM=m`, `CONFIG_VIDEO_BCM2835=m`, `CONFIG_VIDEO_CODEC_BCM2835=m`, `CONFIG_BCM2835_VCHIQ=y`, and `CONFIG_BCM2835_VCHIQ_MMAL=m`.
- `libcamera-0.6.0-r0` includes the Raspberry Pi VC4 IPA module `/usr/lib/libcamera/ipa/ipa_rpi_vc4.so` (and PiSP support).
- `raspberrypi-bootloader-1.20260619-r0` includes `/boot/overlays/pwm-2chan.dtbo`.

Phase-one expectation: on-device video is expected to be functional on Raspberry Pi Zero 2 W, not intentionally degraded. Alpine provides the full VC4 CSI/libcamera/ISP path, the bcm2835-codec H.264 module used by the current worker, and the required PWM overlay. This spike proves package/kernel feasibility but does not replace a physical-board smoke test. The board runbook/release gate must still verify that a camera enumerates through libcamera, `bcm2835-codec` exposes the expected encoder node (the current capture code assumes `/dev/video11`), a short H.264 capture succeeds, and both PWM channels appear after enabling `pwm-2chan`. If Alpine assigns a different V4L2 node, that is a later runtime fix rather than a toolchain fallback.

### Reproduction/check contract for later tasks

Run the builds under `docker run --rm --platform linux/arm64` with the repository mounted read-only and image `docker.io/library/alpine:3.23.5`. Install the component package subset above. Use the existing unit CMake flags, with these Alpine-specific values:

```text
KVS:
  BUILD_TESTING=ON
  TXING_KVS_GRPC_BRIDGE=ON
  TXING_AWS_KVS_WEBRTC_SDK_GIT_TAG=bb106510cf74edd2c24881c1ae94ceaa0083d15c
  TXING_KVS_SYSTEM_CA_CERT_PATH=/etc/ssl/certs/ca-certificates.crt
  OPENSSL_USE_STATIC_LIBS=FALSE
  OPENSSL_INCLUDE_DIR=$(pkg-config --variable=includedir openssl)
  OPENSSL_SSL_LIBRARY=$(pkg-config --variable=libdir openssl)/libssl.so
  OPENSSL_CRYPTO_LIBRARY=$(pkg-config --variable=libdir openssl)/libcrypto.so

Hardware:
  BUILD_TESTING=ON
  TXING_HARDWARE_WORKER_GRPC=ON
```

After each build, run its tests and assert:

```sh
file "$binary"
readelf -l "$binary" | grep -F "/lib/ld-musl-aarch64.so.1"
test -z "$(ldd "$binary" | grep -F "not found")"
```

For the KVS master, also require `ldd` matches for `libcamera.so.0.6` and `libcamera-base.so.0.6`.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed the Alpine/aarch64 de-risking spike without changing product source, firmware, infrastructure, or configuration.

Proved:
- Go daemon, hardware worker, and real-SDK/libcamera KVS master build from unit sources in Alpine 3.23.5 aarch64; their tests pass.
- All three outputs are dynamically linked ARM64 musl ELFs with /lib/ld-musl-aarch64.so.1 and no unresolved ldd entries.
- Alpine 3.23 provides log4cplus, libusrsctp, upstream libcamera 0.6, the Raspberry Pi VC4 camera/ISP and bcm2835-codec kernel modules, and pwm-2chan.dtbo.
- The KVS libcamera ldd contract is libcamera.so.0.6 plus libcamera-base.so.0.6.
- Only the KVS protobuf CMake discovery needs adjustment in the future cyberbrick copy: use CONFIG mode. Go requires external linking in addition to CGO_ENABLED=1; no musl, libcamera API, or KVS SDK source patch was needed.

Durable results are recorded in this task's notes and architecture doc-27, including the exact image pin/digest, package union and observed revisions, build flags, ELF checks, kernel evidence, and phase-one expectation that video is functional.

Validation: Go test suite passed; hardware worker build and 2/2 CTest cases passed; KVS master build and 1/1 CTest passed; file/readelf/ldd checks passed for all executables; Alpine linux-rpi/libcamera/bootloader package contents were inspected directly.

Residual risk: physical Raspberry Pi Zero 2 W validation is still required by the later runbook/hardware-parity tasks, particularly camera enumeration, the /dev/video11 assumption, a short H.264 stream, and PWM channel visibility. No deployment or rollout is required for this documentation-only spike.
<!-- SECTION:FINAL_SUMMARY:END -->
