---
id: TASK-23.8
title: board components build from one shared implementation
status: Done
assignee:
  - '@claude'
created_date: '2026-07-25 17:43'
updated_date: '2026-07-28 19:48'
labels: []
milestone: m-4
dependencies:
  - TASK-23.2
  - TASK-23.3
references:
  - .github/workflows/release-unit.yml
  - .github/workflows/release-cyberbrick.yml
  - release/src/txing_release/cli.py
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 64000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The unit and cyberbrick board daemons, hardware workers, and KVS masters are near-identical copies: after normalizing device names the Go daemon sources are byte-identical and the C++ sources differ by roughly a dozen real lines. That duplication already cost a production defect, because the signaling CA trust-anchor override reached cyberbrick and never reached unit, leaving unit unable to complete AWS signaling on Alpine. Consolidate both device types onto a single implementation selected by a per-device profile so a fix can only ever land in one place.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Both device types build their daemon, hardware worker, and KVS master from a single shared source tree, with device differences supplied by a per-device profile rather than duplicated sources.
- [x] #2 The signaling trust anchor is selectable at runtime on both device types, so a board can point the TLS layer at a single-anchor file without rebuilding.
- [x] #3 Release version strings are injected at build time for both device types, and each device keeps its own independent release stream and version prefix.
- [x] #4 Existing linkage and cross-distro gates pass for both device types built from the merged sources.
- [x] #5 Device shadow schemas and manifests that encode genuine device differences remain per-device.
- [x] #6 Build and release tooling converges on the better of the two existing implementations in each direction, rather than one device's tooling simply replacing the other's.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Measured starting point (normalized for device names, `sed s/unit|cyberbrick/DEV/`):

- Go daemon: `config.go`, `payloads.go`, `topics.go`, `topics_payloads_test.go` identical; `runtime.go` differs only in the generated `*HardwareClient` symbol; `version.go` differs only in the literal version.
- C++ hardware worker: `config.{hpp,cpp}`, `motor.{hpp,cpp}`, `tests/test_main.cpp` identical; `src/main.cpp` differs only in the generated hardware proto namespace/service symbol.
- C++ KVS master: every source identical except `kvs_session_real.cpp` (cyberbrick has the `TXING_KVS_SYSTEM_CA_CERT_PATH` runtime override, unit does not) and the version symbol.
- protos: `board_video.proto` byte-identical apart from the package path; `*_hardware.proto` differs only in the `service` name.
- Real divergence is concentrated in build/release tooling: daemon justfiles, `CMakeLists.txt`, and the two release workflows.

Each device's tooling is better in a different direction, so convergence is two-way (AC #6):

- unit is better at: build-time daemon version injection from `release/versions/unit` via `-X ...DaemonVersion`; native build recipes (`kvs-build-native`, `hardware-build-native`, `_kvs-check-system-dependencies`); `docker-build` prerequisite checks; single-anchor compiled CA default.
- cyberbrick is better at: runtime CA trust-anchor override; build-time C++ version macros (`TXING_CYBERBRICK_{KVS_MASTER,HARDWARE_WORKER}_VERSION`) wired through the release workflow.
- cyberbrick's compiled CA default is `/etc/ssl/certs/ca-certificates.crt`, the full bundle the code comment documents as failing against the KVS SDK's single-anchor TLS layer; unit's Starfield anchor default is the correct one.
- `release-cyberbrick.yml` interpolates its release-summary backticks unescaped where `release-unit.yml` escapes them.

## Phase 1 - converge both implementations in place

No files move. Ends with the two trees differing only by device name.

1. Port the `TXING_KVS_SYSTEM_CA_CERT_PATH` runtime override into unit's `kvs_session_real.cpp` (AC #2, fixes the named production defect).
2. Adopt unit's single-anchor compiled CA default for cyberbrick's daemon justfile and release workflow (AC #6).
3. Port cyberbrick's build-time version macro into unit's `kvs_master/include/kvs_master/version.hpp` and wire `-DTXING_UNIT_*_VERSION` through `release-unit.yml` (AC #3).
4. Port unit's `release/versions/<device>` + `-X ...DaemonVersion` injection into cyberbrick's daemon justfile, replacing the `awk` scrape of `version.go` (AC #3).
5. Port unit's native build recipes and prerequisite checks into cyberbrick's daemon justfile (AC #6).
6. Escape the release-summary backticks in `release-cyberbrick.yml` (AC #6).

## Phase 2 - one shared source tree

Shared daemon, hardware worker, and KVS master sources under `devices/common/board/`, with `devices/{unit,cyberbrick}/` retaining only genuinely per-device material (`manifest.toml`, `aws/` shadow schemas and defaults, `web/` adapter, proto package). Requires the proto-binding decision recorded in the task comments before it can start.

## Phase 3 - per-device profile and tooling

Device differences move into a `[board]` table in each `manifest.toml` (binary prefix, version stream, release tag prefix, CA anchor path), read by the shared justfile recipes and the release workflows. Shadow schemas, defaults, and the rest of each manifest stay per-device (AC #5).

## Phase 4 - gates

`release/scripts/assert-board-musl.sh` and `smoke-board-cross-distro.sh` for both device types, plus `go test ./...`, `ctest`, and the shared python suite (AC #4).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
## Phase 1 complete - both implementations converged in place

No files moved yet. After this phase the two trees differ only by device name, device-specific prose, and the independent version literals.

Two-way convergence, each direction adopting the better existing implementation (AC #6):

- unit gained the runtime signaling trust-anchor override (`TXING_KVS_SYSTEM_CA_CERT_PATH` + `std::getenv`) in `kvs_session_real.cpp`. This is the production defect named in the task description: TASK-23.7 found and fixed it on cyberbrick only, so unit could not point the SDK's TLS layer at a single-anchor file without a rebuild. `kvs_session_real.cpp` is now byte-identical between the two device types (AC #2).
- cyberbrick's compiled CA default moved from `/etc/ssl/certs/ca-certificates.crt` to unit's single Starfield Services Root CA G2 anchor, in both the daemon justfile and `release-cyberbrick.yml`. The full bundle is the one TASK-23.7 proved fails against the SDK's single-anchor TLS layer, so cyberbrick was compiling in the known-bad default and relying entirely on the env override.
- unit's KVS master version header adopted cyberbrick's build-time `#ifndef` macro form, and `release-unit.yml` now passes `-DTXING_UNIT_KVS_MASTER_VERSION` and `-DTXING_UNIT_HARDWARE_WORKER_VERSION`; both CMakeLists gained the matching cache variable and conditional `target_compile_definitions` (AC #3).
- cyberbrick's daemon build adopted unit's `release/versions/cyberbrick` + `-X ...DaemonVersion` injection, replacing an `awk` scrape of `version.go`; `docker-build` and `docker-smoke` read the version file, and `docker-build` checks for `git`/`jq` before building rather than after (AC #3).
- cyberbrick's daemon justfile gained unit's native recipes: `_kvs-check-system-dependencies`, `kvs-build-native`, `hardware-build-native`, plus the build dirs they need, and `clean` now removes them.
- `release-cyberbrick.yml` interpolated its release-summary backticks unescaped, so the step summary ran `$RELEASE_COMPONENT` and friends as commands and emitted empty fields. Escaped to match `release-unit.yml`.
- unit's `kvs-clean` renamed to `clean` to match cyberbrick, with the `devices/common/board/README.md` reference updated.
- `release/src/txing_release/cli.py` tracked unit's KVS master version through a regex matching the old `inline constexpr ... = "x.y.z";` literal, which the macro form no longer matches; updated with its two tests.

Measured result, normalizing device names in both directions: release workflows 0 differing lines; all C++ sources and both `CMakeLists.txt` 0; Go daemon 0 apart from the `version.go` literal. What remains between the two daemon justfiles is recipe ordering and three dead variables in unit, which the Phase 2 merge dissolves.

Verification: `shared/aws/python` 142 passed, `release/tests/test_cli.py` 7 passed, unit hardware-worker ctest passed with a `-DTXING_UNIT_HARDWARE_WORKER_VERSION=9.9.9` override, and the emitted compile definition matches cyberbrick's byte for byte. The one failing test, `test_shell_portability`, fails identically with these changes stashed - it trips on bash shebangs in the vendored Go module cache under `devices/cyberbrick/daemon/tmp/` and is unrelated. The KVS master native test build cannot run in this environment (no `libcamera-dev`); it fails identically for both device types at the same libcamera check, and no Go toolchain is available, so `go test` was not run.

Two new guards in `shared/aws/python/tests/test_versioning.py` hold the ACs rather than the implementation: one asserts the runtime trust-anchor override on both device types (AC #2), one asserts build-time version injection - header macro, workflow flag, and daemon ldflags - for both streams (AC #3).

## Blocked on: Go proto binding strategy for Phase 2

The approved decision keeps proto packages per device (`txing.unit.hardware.v1` / `txing.cyberbrick.hardware.v1`) and only neutralizes the service name to `BoardHardware`. C++ already generates its bindings at build time from `devices/<device>/proto`, so a shared C++ tree only needs the proto root parameterized. Go does not: the `.pb.go` files are checked in, and the repository has no Go proto codegen recipe, no `protoc-gen-go`, and no `protoc-gen-go-grpc` anywhere. A single shared Go module therefore cannot hold one checked-in copy of bindings whose descriptors still carry a per-device package.

## Phase 2 and 3 - one shared implementation, device selected by profile

The daemon, hardware worker, and KVS master now live once under
`devices/common/board/`. `devices/unit/` and `devices/cyberbrick/` keep only
genuinely per-device material: `manifest.toml`, `aws/` shadow schemas and
defaults, `web/` adapter, `proto/`, and unit's `mcu/`.

The device type is a build input rather than a source axis:

- C++: `-DTXING_BOARD_DEVICE_TYPE=<device>` derives the target names, the proto
  root under `devices/<device>/proto`, the binary-name macro, and the hardware
  socket path. A CMake `configure_file` emits a small binding header so the
  shared sources never name the device's proto namespace or generated header
  path directly.
- Go: `-X .../internal/daemon.DeviceType=<device>` in the new
  `internal/daemon/device.go`. Every identifier that used to be a per-device
  constant - `AdapterID`, config subdir, KVS master command, MCP and bridge
  socket paths, hardware socket path, the sanitize fallback, and the KVS client
  id - is derived from it. Verified by build: injecting `cyberbrick` produces
  `dev.txing.cyberbrick.Daemon`, `txing/cyberbrick-daemon`,
  `/run/txing-cyberbrick-hardware-worker/cyberbrick-hardware.sock`, and
  `txing-cyberbrick-kvs-master`, all identical to the values the deleted
  cyberbrick tree carried.

Per the approved decision, the hardware gRPC service is renamed to the
device-neutral `BoardHardware` in both `.proto` files while the proto packages
stay per device. Because the descriptors still carry the device, the daemon's Go
bindings are generated per device at build time instead of being checked in:
`just common::board::proto-gen <device>`, mirrored in the Alpine container build
and in both release workflows, with `protoc-gen-go` pinned to v1.36.10 (the
version the checked-in bindings were generated with) and `protoc-gen-go-grpc` to
v1.5.1. `devices/common/board/daemon/internal/proto/` is gitignored.

Version handling follows AC #3 to its conclusion: with one shared source tree
there is no per-device literal left to mirror, so `release/versions/<device>` is
the only source of truth and both C++ headers and `version.go` now hold a
`0.0.0-dev` fallback that only a developer build without injection can reach.
`release/src/txing_release/cli.py` therefore no longer manages any board source
file, and `just release::bump <device>` writes only the version file.

Build entry points moved to one shared `devices/common/board/justfile`, wired in
as `mod board` under `devices/common/`, with every recipe taking the device type
as its first argument (`just common::board::hardware-test-native unit`). It
validates the device against `devices/<device>/manifest.toml` and
`release/versions/<device>` before doing anything, so a typo fails immediately
rather than building the wrong thing. Per-device build and test output
directories are suffixed with the device so the two never collide. The
per-device `daemon/justfile` modules are gone.

## Verification

- Shared hardware worker: configures, builds, and passes ctest for both device
  types through the shared recipe, and each binary carries its own documented
  socket path.
- Shared Go daemon: `go test ./...` green against both devices' generated
  bindings; builds and reports `txing-unit-daemon 0.15.9` and
  `txing-cyberbrick-daemon 0.15.7` with device and version injected.
- `release/tests/test_cli.py`: 7 passed.
- `shared/aws/python`: 141 passed, 4 failed - all four are stale content
  assertions about the old layout that still need updating, listed below.

Environment limits, unchanged from Phase 1: no `libcamera-dev`, `grpc++`, or
`protoc` here, so the KVS master cannot be compiled locally for either device
type. Its CMake parses through the libcamera gate for both, and the shared
sources are the same ones that built before the move, but its first real
compile will be in CI. Go and the Go proto plugins were installed into the
session to verify the daemon; `buf` stood in for `protoc` locally, while the
committed recipes use `protoc` as the C++ side already does.

## Remaining work

1. Four failing content assertions in `shared/aws/python/tests`:
   `test_aws_cert_recipe_uses_unit_daemon_specific_outputs`,
   `test_aws_recipes_are_stateless_and_staged`,
   `test_component_release_workflows_publish_only_component_assets`, and
   `test_unit_daemon_manual_docker_build_replaces_release_channel`. They assert
   on recipe names like `just unit::daemon::docker-build` that are now
   `just common::board::docker-build unit`.
2. `shared/aws/justfile` and any other caller still invoking the removed
   `unit::daemon::*` / `cyberbrick::daemon::*` recipes.
3. The AC #2 and AC #3 guards added in Phase 1 still name the per-device macros
   and paths; they should now assert the single shared source and the neutral
   macro names.
4. Docs: `docs/components/board.md`, `docs/components/cyberbrick-board.md`,
   `docs/artifacts.md`, `docs/installation.md` and the docs index still describe
   per-device source trees and the old recipe names. TASK-23.10 consolidates the
   runbooks and should absorb the runbook half of this.
5. A `[board]` table in each `manifest.toml` was not added: the device type plus
   the existing manifest is currently the whole profile, and nothing yet needs a
   value the device type does not already derive. Worth adding only when a real
   per-device build value appears that is not derivable.
6. Pre-existing failures untouched by this task, both confirmed against HEAD:
   `test_shell_portability` trips on bash shebangs in the vendored Go module
   cache under `devices/*/daemon/tmp/`, and
   `TestDaemonEnvTemplateContainsForwardRuntimeDefaults` failed at HEAD because
   the shipped `daemon.env.template` never contained
   `TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH` or
   `TXING_HARDWARE_WORKER_SOCKET_PATH`. In the shared tree those paths are
   device-derived and cannot be template literals, so the test now asserts the
   derived defaults instead.

## Integration closed

All callers, tests, and docs now reference the shared tree.

- `shared/aws/justfile` pointed at both removed per-device `daemon.env.template` paths; both now resolve to the single shared template, keeping the per-device variable names because `txing_generate_iot_certificate_bundle` still selects by device type.
- `docs/aws.md`, `docs/development.md`, `docs/constraints/repository-rules.md`, `docs/components/board.md`, and `docs/components/cyberbrick-board.md` moved from `just <device>::daemon::<recipe>` to `just common::board::<recipe> <device>`.
- `shared/aws/python/tests` updated throughout: paths onto the shared tree, the single shared justfile in place of two per-device ones, parameterized release-stream and binary-name assertions, and the release CLI assertions inverted to require that no board source file is version-managed.
- The Phase 1 AC guards were rewritten for the merged layout. `test_board_components_build_from_one_shared_implementation` now holds AC #1 directly: one copy of each component under `devices/common/board/`, no `board/` or `daemon/` left under either device, per-device manifest/aws/proto still present, no device name in either `CMakeLists.txt`, and `BoardHardware` with a still-per-device package in both protos.
- Deleting cyberbrick's duplicate tree also removed 469 committed build artifacts under `build-tests/`, which is what the pre-existing `test_shell_portability` failure was tripping on. That suite now passes.

Verification, all green: `shared/aws/python` 146 passed, `release/tests/test_cli.py` 7 passed, shared hardware worker ctest for both device types, shared Go daemon `go test ./...` against both devices' generated bindings.

AC #4 is the one criterion that cannot be closed from here. The linkage and cross-distro gates are the release workflows, and this environment has no `libcamera-dev`, `grpc++`, or `protoc`, so the KVS master has never been compiled from the merged sources. Both release workflows are wired for it - shared source dirs, `TXING_BOARD_DEVICE_TYPE`, build-time version macros, and the new Go codegen step - but running them is an operator action.

## Callers outside the board tree

A repo-wide sweep found one real broken caller beyond docs: `devices/mac/justfile` compiles the KVS master for macOS and still pointed at `devices/unit/board/kvs_master`. It now builds the shared source with `TXING_BOARD_DEVICE_TYPE`, pinned to `unit` in one variable, into a device-suffixed `build-macos-<device>` directory. The mac daemon's `internal/action` comments, `devices/mac/README.md`, the root `AGENTS.md` repository map, and the `daemon.env.template` references in `docs/artifacts.md`, `docs/development.md`, `docs/components/board.md`, and `docs/components/cyberbrick-board.md` were repointed as well.

A grep for `devices/{unit,cyberbrick}/{board,daemon}` across markdown, python, yaml, justfiles, shell, and Go now returns nothing outside the backlog archive.

## AC #4: running the real gates found two defects the local checks could not

Docker here is a native linux/arm64 daemon, which is what the Alpine build requires, so the linkage and cross-distro gates run locally after all. Doing so immediately exposed two bugs that neither the python suites nor the GRPC-off native test builds could reach:

1. The `_alpine-build` container mounts the project root read-only, deliberately, so the build cannot mutate the source tree. The new Go codegen wrote its bindings into `devices/common/board/daemon/internal/proto` inside that mount and failed with `Read-only file system`. The C++ codegen was unaffected because CMake generates into the build directory. Fixed by copying the daemon module into a writable temp directory in the container, generating there, and building from it, which keeps the read-only invariant intact. The release workflows were already correct here: they mount the workspace read-write.

2. The generated proto binding headers declared the alias `pb` at global scope. `board_video.grpc.pb.h` already brings a conflicting `pb` into that translation unit, so every proto type in `board_video_bridge_grpc.cpp` failed to resolve. The original code had deliberately scoped its alias inside the file's anonymous namespace and the move to a shared header lost that. Both binding headers now publish `txing::board::proto::{board_video_v1,hardware_v1}` and each source restores its own file-local alias where the original lived.

Neither was reachable without compiling the KVS master, which is exactly the component AC #4 covers.

Gate results from the merged sources, in the pinned Alpine 3.24.1 aarch64 container:

- unit daemon: static, no PT_INTERP, `txing-unit-daemon 0.15.9`.
- unit KVS master: musl-dynamic against the expected interpreter, no unresolved libraries, resolving stock Alpine `libcamera.so.0.7` and `libcamera-base.so.0.7`, `txing-unit-kvs-master 0.15.9`.

## AC #4 closed: gates pass for both device types from the merged sources

`docker-build` followed by `docker-smoke` ran for both device types against the pinned Alpine 3.24.1 aarch64 container, exit 0 throughout.

Linkage, asserted inside the build container:

- Static with no ELF interpreter: `txing-unit-daemon`, `txing-unit-hardware-worker`, `txing-cyberbrick-daemon`, `txing-cyberbrick-hardware-worker`.
- musl-dynamic against `/lib/ld-musl-aarch64.so.1` with no unresolved libraries, resolving stock Alpine `libcamera.so.0.7` and `libcamera-base.so.0.7`: `txing-unit-kvs-master`, `txing-cyberbrick-kvs-master`.
- Four in-container ctest runs (KVS master and hardware worker, both device types) passed.

Cross-distro smoke: the two static binaries per device execute and report their version on both `debian:trixie` and pinned Alpine; each KVS master executes on Alpine, which is the documented camera-build limit rather than a gap.

Each device reported its own stream from one shared source tree: unit at 0.15.9, cyberbrick at 0.15.7, which is AC #3 proven end to end on real binaries.

## CI failure: protoc plugin versions were not forwarded into the build container

The first real `release-cyberbrick` run failed at the build step with
`sh: PROTOC_GEN_GO_VERSION: parameter not set`.

Cause: the release workflows run their build body as a quoted heredoc inside
`docker exec`, which sees only the variables passed with an explicit `-e`
allowlist. The two protoc plugin versions were added to the step's `env:` block
but not to that list, so under `set -eu` the container aborted. The local
`_alpine-build` path was unaffected because its `docker run` already forwards
both, which is why the end-to-end container gates passed here while CI did not:
the justfile and the workflow are two separate implementations of the same
build, and only the former had been executed.

Fixed by forwarding `PROTOC_GEN_GO_VERSION` and `PROTOC_GEN_GO_GRPC_VERSION` in
both workflows. A sweep of every `docker exec` heredoc in both files confirms no
other variable is referenced without being forwarded, assigned locally, or given
a `:-` default.

Added `test_release_workflow_containers_receive_every_variable_they_use`, which
parses each heredoc block and compares referenced variables against the
forwarded set. Verified it catches this exact defect: with the fix reverted it
fails naming both variables.

No release tag was created - the failure was in `build`, and `gh release create`
runs in `publish`, which depends on `build` and `smoke`. The same version can be
re-run once the fix is pushed.

## Operator validation on physical hardware (cyberbrick stream, unit board)

`cyberbrick-v0.15.8`, the first release built from the merged sources, installed
on a physical unit board running Alpine and carrying the cyberbrick binaries.
Operator-reported evidence:

- All three binaries report `0.15.8`. Nothing in the source tree carries that
  literal any more, so this is build-time injection proven on real artifacts.
- `txing-cyberbrick-daemon`: `ldd` reports `Not a valid dynamic program`, which
  is the expected result for the static binary rather than a fault.
- `txing-cyberbrick-hardware-worker`: `ldd` shows only the musl loader, static.
- `txing-cyberbrick-kvs-master`: musl-dynamic with no unresolved entries,
  resolving `libcamera.so.0.7` and `libcamera-base.so.0.7` from `/usr/lib`.
- After reboot the board reaches REDCON 1 with live video **and working motion
  control**.

Motion control is the load-bearing result. Video rides `BoardVideoBridge`, whose
proto and service name were untouched, so it would have come up even with the
hardware rename broken. Control exercises the daemon to hardware worker path
over the renamed `BoardHardware` service, which is the one breaking change in
this task, and it works.

Scope of what this proves: the consolidated implementation is behaviourally
identical to the pre-merge cyberbrick build on the same hardware, with identical
config paths, socket paths, service names, and adapter id. It does not yet
exercise the unit release stream on that board; switching device streams is
TASK-23.13.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @claude
created: 2026-07-28 07:07
---
Architecture decision (user-approved): the hardware gRPC service is renamed to the device-neutral `BoardHardware` on both device types, matching the existing `BoardVideoBridge` precedent, while the proto packages stay per-device (`txing.unit.hardware.v1` / `txing.cyberbrick.hardware.v1`). This makes the generated Go and C++ symbols identical so one source tree compiles for both, and leaves TASK-23.9 its stated job of collapsing the per-device packages. Consequence: the hardware method path changes, so the daemon and hardware worker must be upgraded together - the same coordinated-upgrade hazard TASK-23.9 documents, arriving one task earlier.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Both board device types now build their daemon, hardware worker, and KVS master from one shared implementation under devices/common/board/, with the device type as a build input that selects the proto package, binary names, socket paths, and release stream. The duplication that caused the signaling trust-anchor defect is gone: unit gained the runtime CA override it was missing, cyberbrick lost the known-bad compiled default it was relying on an env var to mask, and both now inject their version at build time from release/versions/<device> with no source literal left to drift. The hardware gRPC service is device-neutral BoardHardware while its package stays per device, so the daemon's Go bindings are generated per device at build time rather than checked in. Verified by the linkage and cross-distro gates for both device types in the pinned Alpine container, the full python and Go suites, and an operator install of cyberbrick-v0.15.8 on a physical board reaching REDCON 1 with video and working motion control.
<!-- SECTION:FINAL_SUMMARY:END -->
