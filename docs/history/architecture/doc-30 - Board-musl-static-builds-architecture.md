---
id: doc-30
title: Board musl static builds architecture
type: specification
created_date: '2026-07-21 10:58'
updated_date: '2026-07-21 11:41'
tags:
  - board
  - alpine
  - musl
  - static-linking
---
# Board musl static builds architecture

## Problem

Unit's board pipeline is the last Debian-based build in the repository: `.github/workflows/release-unit.yml` and `devices/unit/daemon/justfile` build the two C++ workers in `debian:trixie` containers with the Raspberry Pi apt repository pinned so the KVS master links the RPi libcamera fork. The long-term direction is to move completely off Debian — but not now: Debian (Raspberry Pi OS) boards remain in service during the transition, so shipped board components must run on both Debian and Alpine hosts.

## Current state

- **unit (Debian, being retired)**: Go daemon is already `CGO_ENABLED=0` static (built on the Ubuntu runner). The C++ workers build in `debian:trixie` containers; `release-unit.yml` and the justfile's `_cpp-build-trixie`/`docker-build` recipes write a raspi apt source (`archive.raspberrypi.com`, Pin-Priority 1001 for `libcamera*`) and assert `libcamera.so.0.7`/`libcamera-base.so.0.7`.
- **cyberbrick (Alpine, reference)**: all three binaries build in pinned `docker.io/library/alpine:3.23.5` (`linux/arm64`, digest `sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40`), everything musl-dynamic per doc-29 (Go via `CGO_ENABLED=1` + `-linkmode=external`), KVS master against stock Alpine libcamera 0.6. `release/scripts/assert-cyberbrick-musl.sh` enforces the ABI.
- **TASK-22.1** proved the whole board stack builds on Alpine with exactly one source patch: `find_package(Protobuf CONFIG REQUIRED)` in the KVS master CMake. The proven apk package union and assertion recipes are recorded in doc-27.

## Why musl-dynamic cannot serve Debian boards

- Debian ships a `musl` package providing only the loader and libc (`/lib/ld-musl-aarch64.so.1`): a musl-dynamic binary whose sole dependency is musl libc can run on Debian after `apt install musl`.
- Debian ships **no musl-built libraries**. Its libcamera/gRPC/protobuf/OpenSSL are glibc builds in `/usr/lib/aarch64-linux-gnu/`, which the musl loader neither searches (default path `/lib:/usr/local/lib:/usr/lib`, override via `/etc/ld-musl-aarch64.path`) nor could use (different libc ABI).
- Running Alpine-built dynamic binaries on Debian would require shipping the Alpine `.so` closure — a de facto Alpine chroot, not a standard installation. Rejected.
- Consequence: **only fully static musl binaries run unmodified on both distros**; anything musl-dynamic beyond bare libc is Alpine-only.

## Target linkage contract

| Component | Linkage | Runs on |
|---|---|---|
| Go daemons (unit, cyberbrick) | `CGO_ENABLED=0` static | Debian + Alpine |
| hardware worker | fully static musl (static protobuf/gRPC) | Debian + Alpine |
| KVS master (camera) | musl-dynamic; stock Alpine libcamera, soname-asserted (currently `libcamera.so.0.6`) | Alpine only |

- Single pinned Alpine image across every board build path (justfiles and workflows for both devices), currently `alpine:3.23.5`.
- Assertion recipe per linkage kind: static → `file`/`readelf -l` show a statically linked aarch64 ELF with no `INTERP` segment; musl-dynamic → interpreter `/lib/ld-musl-aarch64.so.1`, every `ldd` entry resolves, libcamera sonames present.
- Artifact names, single-root-entry tarballs, and immutable `unit-v*`/`cyberbrick-v*` tags are unchanged; the assert script generalizes to a shared board script parameterized by linkage kind.

## Transition strategy (Debian wind-down)

- The Debian toolchain is removed from CI and justfiles immediately; no new Debian builds are produced.
- Debian boards keep receiving daemon and hardware worker updates — the static binaries depend only on the kernel.
- Camera on Debian freezes at the last Debian-built KVS master release; new camera builds are Alpine-only. A board rejoins the camera update stream when it is reimaged to Alpine (cyberbrick runbook pattern).
- End state: all boards on Alpine, the Debian path disappears without a big-bang reimage.

## Open risks (spike TASK-23.1 resolves)

- **Static protobuf/gRPC on Alpine**: apk `grpc-dev` may not ship static libraries. Fallback: build protobuf/gRPC statically from source via `ExternalProject_Add`, exactly as the KVS WebRTC SDK is already built (`-DBUILD_STATIC_LIBS=ON`).
- **Static Go daemon on Alpine**: expected trivial with `CGO_ENABLED=0`; verify nothing still requires `-linkmode=external`.
- **Cross-userland execution**: verify the static binaries execute in both `debian:trixie` and `alpine:3.23.5` containers (kernel-only dependency expected).

## Proven static toolchain contract (TASK-23.1)

Spike executed 2026-07-21 on `docker.io/library/alpine:3.23.5` (`linux/arm64`), observed digest `sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40` — identical to the digest doc-27 pinned. Native aarch64 Docker daemon; repository mounted read-only; **no product sources or build files were modified**.

- **apk has no static gRPC stack.** `grpc-dev`/`protobuf-dev` install only `libcares.a` and `libupb.a`; v3.23 main/community carries no `*-static` package for grpc, protobuf, or abseil-cpp. Relevant static packages that do exist: `zlib-static`, `openssl-libs-static` (plus `libcares.a` via `c-ares-dev`). The "static from apk" branch is therefore closed; the source-build fallback is the contract.
- **Fallback proven: static-only source builds into an isolated prefix**, tags pinned to the apk package versions so device and build ABI expectations stay aligned: abseil-cpp `20250814.1`, protobuf `v31.1`, re2 `2025-11-05`, c-ares `v1.34.8` (`-DCARES_STATIC=ON -DCARES_SHARED=OFF`), grpc `v1.76.0` (shallow clone plus proto submodules `xds`, `envoy-api`, `googleapis`, `opencensus-proto`, `protoc-gen-validate`; all dependency providers `package`; non-C++ codegen plugins off). Common flags: `-DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_CXX_STANDARD=17`, with `-DOPENSSL_USE_STATIC_LIBS=TRUE -DZLIB_USE_STATIC_LIBS=ON` steering FindOpenSSL/FindZLIB to the apk static archives. Roughly 35 minutes on 8 aarch64 cores.
- **The hardware worker builds fully static from unmodified sources** using only external configuration: `-DCMAKE_PREFIX_PATH=<prefix> -DCMAKE_EXE_LINKER_FLAGS=-static -DOPENSSL_USE_STATIC_LIBS=TRUE -DZLIB_USE_STATIC_LIBS=ON`. The CONFIG-mode `find_package(Protobuf)`/`find_package(gRPC)` in the existing CMakeLists resolve to the static install untouched; `protoc` and `grpc_cpp_plugin` come from the same prefix. Result: `txing-unit-hardware-worker 0.15.4`, ARM aarch64, `static-pie linked`, no `PT_INTERP`.
- **apk build package set** (beyond the source-built stack): `build-base cmake git pkgconf linux-headers binutils file curl openssl-dev openssl-libs-static zlib-dev zlib-static`, plus `go` for the daemons.
- **Static-PIE finding.** Alpine gcc defaults to PIE, so `-static` produces a static-PIE: `file` reports `static-pie linked` and the ELF type is `DYN`, yet there is no interpreter and no shared-library dependency. Linkage assertions must accept `statically linked|static-pie linked`; the hard invariants are the absence of a `PT_INTERP` program header and successful execution on a bare non-musl userland. `-static -no-pie` yields classic `statically linked` ET_EXEC where determinism is preferred.
- **Go daemons.** apk `go` 1.25.10: `CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath` builds both `txing-unit-daemon` and `txing-cyberbrick-daemon` as `statically linked` aarch64 ELFs with no INTERP — no `-linkmode=external` requirement remains once musl-dynamic linkage is no longer the goal.
- **Cross-distro smoke.** All three binaries executed `--version` successfully in bare `debian:trixie` and `alpine:3.23.5` containers with zero packages installed — the static artifacts depend only on the kernel.
- **KVS master unaffected.** The spike changed no shared sources, CMake files, justfiles, or workflows; the static stack lives in an isolated prefix selected purely by external flags, so the musl-dynamic KVS master build contract from doc-27 is untouched.
- **Assertion recipe** (per static binary): `file` matches `ELF 64-bit LSB.*ARM aarch64` and `statically linked|static-pie linked`; `readelf -l` contains no `INTERP`; the binary executes `--version` in bare `debian:trixie` and pinned Alpine containers.

## GitHub issue references

- [#78 — Static musl toolchain is proven for the board stack](https://github.com/mparkachov/txing/issues/78) (migrated from `TASK-23.1`)
- [#84 — unit board daemons build as Alpine musl binaries](https://github.com/mparkachov/txing/issues/84) (migrated from `TASK-23.2`)
- [#88 — unit release pipeline publishes Alpine artifacts](https://github.com/mparkachov/txing/issues/88) (migrated from `TASK-23.4`)
