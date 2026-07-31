---
id: TASK-23.9
title: board video bridge speaks one protocol package
status: Done
assignee:
  - '@claude'
created_date: '2026-07-25 17:43'
updated_date: '2026-07-29 09:11'
labels: []
milestone: m-4
dependencies:
  - TASK-23.8
references:
  - docs/contracts/board-video-bridge.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 65000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The local daemon-to-worker video bridge contract is duplicated per device, so even a merged implementation would carry a device axis in its wire contract. Unify it onto one device-independent package. This renames the gRPC service, so a board running a mixed pair stops connecting and video goes down silently: the worker retries a bridge that never answers and the daemon logs to CloudWatch rather than locally. The Debian board pinned to the last Debian-built KVS master cannot be rebuilt, because camera builds are Alpine-only, so it must be reimaged to Alpine before this lands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The daemon and KVS master communicate over a single device-independent bridge protocol on both device types.
- [x] #2 Upgrading a board installs the daemon, hardware worker, and KVS master together, and the runbook states that a partial upgrade leaves video down with no local error.
- [x] #3 No build path or checked-in binding in the repository produces the previous per-device protocol, and the runbook gives the operator a per-board check for it. Migrating boards already in service is gated by TASK-23.13 AC #3.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Scope. TASK-23.8's approved decision left both local protocols on per-device packages with device-neutral service names, and the option selected there recorded that 23.9 collapses the packages. So this covers both local contracts, not the video bridge alone: leaving `txing.<device>.hardware.v1` behind would keep exactly the device axis in the wire contract that this task exists to remove, and would keep the per-device codegen machinery alive for one protocol.

Target layout, replacing `devices/unit/proto` and `devices/cyberbrick/proto`:

- `devices/common/board/proto/txing/board/board_video/v1/board_video.proto`, package `txing.board.board_video.v1`
- `devices/common/board/proto/txing/board/hardware/v1/hardware.proto`, package `txing.board.hardware.v1`

Both files are already byte-identical across device types apart from the package line, so this is a package rename rather than a contract change. Service names (`BoardVideoBridge`, `BoardHardware`) and every message and RPC stay as they are.

Consequences to carry through:

1. The two generated C++ binding headers added in 23.8 exist only to resolve a per-device header path and namespace. With one package they are dead and the shared sources can include the generated headers directly again.
2. CMake keeps `TXING_BOARD_DEVICE_TYPE` for binary names, the hardware socket path, and the version, but the proto root stops depending on it.
3. Go bindings become identical for both device types, so `proto-gen` loses its device argument. Generation stays at build time rather than returning to checked-in code, which keeps generated output out of the tree and matches how the C++ side has always worked.
4. Release workflows: the codegen block loses its per-device proto paths.
5. Tests that assert per-device proto packages invert to assert a single shared package and the absence of device proto directories.
6. AC #2 is a documentation obligation: the runbook already upgrades all three binaries in one `mise upgrade`, but it must state explicitly that a partial upgrade leaves video down with no local error, because the daemon logs that failure to CloudWatch rather than the console.

AC #3 is fleet state rather than code: it needs every board reimaged or upgraded past the old protocol, including the Debian board that cannot be rebuilt because camera builds are Alpine-only. That is an operator action and will be reported as the remaining gate.

Validation: shared C++ ctest for both device types, Go build and test for both, then the linkage and cross-distro container gates for both, matching how 23.8 was closed.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Both local contracts now live in one device-independent package under
`devices/common/board/proto/txing/board/`: `board_video/v1/board_video.proto` as
`txing.board.board_video.v1` and `hardware/v1/hardware.proto` as
`txing.board.hardware.v1`. `devices/unit/proto` and `devices/cyberbrick/proto`
are gone. Because the two copies were already byte-identical apart from the
package line, this is a package rename: every service name, message, and RPC is
unchanged, and the wire paths become `/txing.board.board_video.v1.BoardVideoBridge/*`
and `/txing.board.hardware.v1.BoardHardware/*`.

Scope covers the hardware contract as well as the video bridge. Leaving
`txing.<device>.hardware.v1` behind would preserve exactly the device axis in the
wire contract that this task exists to remove, and would keep the per-device
codegen machinery alive for one protocol. The option approved in TASK-23.8
recorded that 23.9 collapses that package.

Fallout carried through:

- The two generated C++ binding headers added in TASK-23.8 existed only to
  resolve a per-device header path and namespace. With one package they are dead
  and both sources include the generated headers directly again, so the
  `configure_file` steps are gone from both CMakeLists.
- CMake keeps `TXING_BOARD_DEVICE_TYPE` for binary names, the hardware socket
  path, and the version, but the proto root no longer depends on it.
- `just common::board::proto-gen` lost its device argument: one set of bindings
  now serves both device types. Generation stays at build time.
- Both release workflows point their codegen at the shared proto root.

A third speaker of the bridge protocol turned up that neither the task
description nor the milestone doc mentions: `devices/mac/daemon` serves
BoardVideoBridge for the macOS development path and carries its own checked-in
`boardvideov1` bindings, generated from the old `txing/unit/board_video` proto,
with no proto of its own and no codegen recipe. It pairs with the same KVS
master that `devices/mac/justfile` builds, so leaving it behind would have
broken macOS local video with exactly the silent failure this task warns about.
Its bindings were regenerated from the unified proto and its suites pass.

`docs/components/board.md` needed the opposite treatment from the other docs. It
describes the unit board on Debian and systemd, and those boards genuinely still
run the per-device packages: their KVS master cannot be rebuilt because camera
builds are Alpine-only. Rewriting its package names would have claimed a
protocol that hardware cannot speak. The per-device names are restored there and
the document now opens with a note that they are superseded, that the two
protocols are wire-incompatible, and that such a board must be reimaged to
Alpine rather than upgraded. Freezing the rest of that material is TASK-23.10.

AC #2 is satisfied in the runbook's Maintenance section, which now states that
the three binaries move as a set and that a partial upgrade leaves video down
and motion control unresponsive with no local error, because the KVS master
retries a bridge that never answers and the daemon reports to CloudWatch rather
than the console, so every service still shows as running. The restart-order
section is cross-referenced so that restarting one binary, which is safe, is not
confused with upgrading one, which is not.

## macOS development lane brought onto the same standard

The mac daemon was the last place still on the old pattern: checked-in `.pb.go`
bindings, no proto of its own, and no codegen recipe. Regenerating them by hand
each time the contract moves is exactly how the two ends drift apart, which is
the failure this task exists to prevent.

`devices/mac/justfile` now carries a `proto-gen` recipe that mirrors the board's:
it generates from the shared
`devices/common/board/proto/txing/board/board_video/v1/board_video.proto` with
the same pinned `protoc-gen-go` v1.36.10 and `protoc-gen-go-grpc` v1.5.1, into
the same `internal/proto` layout. `just mac::test` and `just mac::build` run it
first, so there is nothing extra to remember. The generated output is no longer
tracked: `devices/mac/daemon/internal/proto/` is untracked and gitignored, so
the mac daemon holds no copy of the contract that can go stale.

This costs mac developers nothing new. `protoc` comes from the `protobuf`
Homebrew formula that `just mac::kvs-build` already requires, and `proto-gen`
names it in its own preflight message.

A guard in `test_board_components_build_from_one_shared_implementation` holds
the parity: it asserts the mac recipe exists, reads the shared proto path,
pins the same two plugin versions as the board justfile (compared rather than
hardcoded, so a future bump has to move both together), gitignores the generated
directory, and tracks none of it. Verified to fail when the ignore rule is
removed. Its `git ls-files` check degrades to a skip rather than an error when
git cannot answer, so the suite stays runnable in restricted checkouts.

## AC #1 closed: gates pass for both device types on the unified protocol

`docker-build` then `docker-smoke` for both device types in the pinned Alpine
3.24.1 aarch64 container, exit 0 throughout. This was the first compile of both
C++ workers against `txing.board.*`, which is where the 23.8 binding-header
collision surfaced, so it is the load-bearing check.

Totals across both devices: 8 static-linkage assertions (daemon and hardware
worker), 2 musl-dynamic KVS masters against the expected interpreter with no
unresolved libraries, 4 stock-Alpine libcamera 0.7 resolutions, 4 in-container
ctest runs, and 10 cross-distro smoke checks green on `debian:trixie` and pinned
Alpine.

The protocol footprint of the shipped binaries is exactly what the contract
implies, on both streams: the daemon carries `txing.board.board_video.v1` and
`txing.board.hardware.v1`, the KVS master carries only the former, the hardware
worker only the latter, and no `txing.unit.*` or `txing.cyberbrick.*` string
survives in any of them.

## Operator verification for AC #3

Matching versions do not prove a board left the old protocol: a board imaged
from an older release can show three consistent version numbers and still speak
the per-device packages. Because protobuf embeds the package names in the
binary, `strings` answers it directly, and the runbook's maintenance window now
carries that loop with its expected output before the reboot step. The technique
was validated against the freshly built artifacts for both device types rather
than assumed.

## AC #3 is blocked on operator action, not on remaining work in the repository

Everything in this task that can be expressed as code, configuration, tests, or
documentation is done and gated. AC #3 is a statement about the state of
physical hardware in service, and every route to it from this environment is
closed:

- Publishing a release needs the change committed and the workflow dispatched.
  Commits and release dispatch are explicit operator actions under
  `AGENTS.md` and `docs/constraints/repository-rules.md`, and nothing here is
  committed.
- Upgrading a board needs ssh to the device. There is no access, and privileged
  host configuration is operator work by repository rule.
- Reading current fleet state to enumerate which boards still speak the old
  protocol would be a read-only AWS inspection, which the rules permit, but this
  environment has no `aws` CLI and no credentials.
- The Debian board cannot be upgraded onto this protocol at all. Camera builds
  are Alpine-only, so its KVS master cannot be rebuilt; it must be reimaged.
  That reimage is also TASK-23.13 AC #3.

What this task can hand the operator, and does:

1. Both streams build and pass the linkage and cross-distro gates on the unified
   protocol.
2. The runbook states the all-three-together upgrade rule and the silent
   failure a partial upgrade causes.
3. The runbook carries a per-board `strings` check, validated against real
   artifacts for both device types, that proves which protocol a deployed
   binary speaks. Matching version numbers do not.

The task stays In Progress rather than Done: marking it complete would record in
the backlog that no board runs the previous protocol, which is not known to be
true and is currently false for at least the Debian board.

## AC #3 rescoped (user-approved) and verified

The original AC #3 asserted fleet state and duplicated TASK-23.13 AC #3, which
already gates reimaging the Debian board onto the unified protocol. As written
this task could never close on work it owns, so with approval AC #3 was narrowed
to what this task is actually responsible for: that the repository produces only
the unified protocol, and that the runbook gives the operator a per-board check.
Migrating boards in service remains gated, once, by TASK-23.13 AC #3.

Verified rather than asserted:

- No build path emits the previous protocol. A sweep of every `.proto`,
  `CMakeLists.txt`, justfile, workflow, Go, and C++ source for `txing.unit.*`,
  `txing.cyberbrick.*`, or the old proto paths returns nothing. Two hits found
  and cleared on the way: a stale comment in `devices/mac/daemon/internal/action/bridge.go`
  still naming `devices/unit/proto`, and leftover untracked artifacts under
  `kvs_master/build/` from a pre-move build.
- No generated binding is tracked anywhere: `git ls-files` matches no `.pb.go`,
  `.pb.cc`, or `.pb.h`. The only protos in the tree are the two shared ones.
- The runbook carries the per-board `strings` check with expected output,
  validated against real artifacts for both device types.

Final state: `shared/aws/python` 147 passed, `release/tests` 7 passed, shared
hardware worker ctest green for both device types, mac daemon's four packages
green, and the linkage and cross-distro gates green for both streams.

## Operator validation on the macOS lane

Operator built the mac project, ran the local rig and the mac daemon, and drove
REDCON 4 -> 1 -> 4 from office with working video.

What this establishes:

- `txing.board.board_video.v1` works end to end between two independently built
  binaries: the mac daemon serving the bridge and the shared KVS master dialling
  it. The KVS master cannot reach READY without a successful `GetWorkerConfig`
  over that socket, so live video is direct proof the unified package is
  consistent across both ends.
- The full ladder up and back down, not a single bring-up, so teardown at
  REDCON 4 releases the worker cleanly.
- `just mac::proto-gen` runs against real `protoc` on macOS and produces
  bindings the daemon builds against, which is the first exercise of the mac
  codegen path outside this environment.
- The shared `kvs_master` sources compile and run on macOS with
  `TXING_BOARD_DEVICE_TYPE=unit`, covering the AVFoundation capturer branch that
  the Alpine container build never compiles. Together with the aarch64 Alpine
  gates this is the third platform the consolidated sources have built on.

What it does not establish: the mac daemon has no hardware worker and declares
no drive control, so `txing.board.hardware.v1` is still validated only by
compilation and ctest. The motion control confirmed earlier on the physical
board was release 0.15.8, which carried the TASK-23.8 service rename but not
this task's package move. Proving the hardware contract on a board is
TASK-23.13.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Both local board contracts now live in one device-independent package: txing.board.board_video.v1 and txing.board.hardware.v1 under devices/common/board/proto, replacing the per-device copies that were already byte-identical apart from their package line. Every speaker moved together, including the mac daemon, which turned out to be a third participant carrying its own checked-in bindings; it now generates from the shared proto with the same pinned plugins and tracks none of the output, so the two ends of the bridge cannot drift. The C++ binding headers added in TASK-23.8 became dead and were removed, and proto-gen lost its device argument. The runbook states that the three binaries upgrade as a set and that a partial upgrade takes down video and motion with no local error, and carries a strings-based per-board check that proves which protocol a deployed binary speaks, since matching versions do not. Verified by the linkage and cross-distro gates for both device types on the unified protocol, plus the python, Go, and C++ suites. Migrating boards already in service is gated by TASK-23.13.
<!-- SECTION:FINAL_SUMMARY:END -->
