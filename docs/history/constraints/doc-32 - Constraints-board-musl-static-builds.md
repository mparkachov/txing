---
id: doc-32
title: 'Constraints: board musl static builds'
type: guide
created_date: '2026-07-21 10:58'
updated_date: '2026-07-21 10:58'
tags:
  - board
  - alpine
  - musl
  - constraints
---
# Constraints: board musl static builds

Durable rules for building and shipping board binaries after the m-4 migration. These extend, and never relax, the repository-wide rules in `docs/agent-guidance/editing-boundaries.md`. They supersede the "dynamically linked against musl" ABI clause of `doc-29 - Constraints-cyberbrick-Alpine-board.md` (TASK-23.3 amends that text); doc-29's unit-parity and operations rules (OpenRC, read-only root, manual mise updates) remain in force for cyberbrick.

## ABI and toolchain

- Every board binary is built in the **single pinned Alpine version**. The justfile build images (unit and cyberbrick), the release workflow containers, and the runbooks' on-device apk branch must name the same Alpine release; bumping it is one coordinated change across all of them plus new releases.
- Linkage is **static-first**: Go daemons build `CGO_ENABLED=0`; the hardware worker links fully static against musl (static protobuf/gRPC). CI must assert static linkage (statically linked aarch64 ELF, no `INTERP` program header); dynamic linkage of these binaries is a release blocker.
- The **KVS master is the only musl-dynamic binary**: interpreter `/lib/ld-musl-aarch64.so.1`, every `ldd` entry resolves, and the stock Alpine (upstream) libcamera soname is asserted. libcamera apk upgrades that change the soname require a rebuild and release.
- **No Debian toolchain anywhere**: no Debian containers and no Raspberry Pi apt repositories in any build path, CI or local. Alpine-compatibility source patches live in the device tree they serve and must not change behavior for other devices.

## Debian transition

- Debian boards are supported only as consumers of the static binaries; they install no Alpine libraries and need no musl loader.
- Camera updates are Alpine-only. Debian boards stay pinned to the last Debian-built KVS master release; no new Debian-targeted build infrastructure may be added. A board regains camera updates by being reimaged to Alpine per the board runbook.
- Cross-distro smoke (static binaries executed in `debian:trixie` and the pinned Alpine container) must remain in the release workflows for as long as Debian boards are in service.

## Operations

- Install and update remain manual and operator-driven (mise pull from immutable `unit-v*`/`cyberbrick-v*` GitHub releases); no auto-update mechanisms.
- Repository-wide gates apply unchanged: no automatic `git commit`, no mutating AWS commands from agents, no firmware flashing by agents.
