---
id: doc-31
title: 'Milestone: Board musl static builds'
type: specification
created_date: '2026-07-21 10:58'
updated_date: '2026-07-21 10:58'
tags:
  - board
  - alpine
  - musl
  - milestone
---
# Milestone: Board musl static builds

## Goal

Complete the migration of board component builds off Debian: every board binary for unit and cyberbrick is built in the single pinned Alpine/musl toolchain, statically linked wherever possible so the shipped daemon and hardware worker run unmodified on both existing Debian boards and Alpine boards. The camera KVS master is the sole exception — it cannot be linked statically and stays musl-dynamic against stock Alpine libcamera, making new camera builds Alpine-only.

## Scope

This milestone covers the static-musl toolchain validation spike, replacing unit's `debian:trixie`+raspi-repo build paths (justfile recipes and release workflow) with Alpine recipes mirroring cyberbrick, aligning cyberbrick's Go daemon and hardware worker to the static-where-possible policy (amending doc-29's musl-dynamic-only clause), a shared linkage assert script covering both linkage kinds, CI and local cross-distro smoke runs, documentation updates including the Debian transition guidance, and operator-run validation on physical Debian and Alpine boards.

This milestone does not cover reimaging existing Debian boards (operator-scheduled, per board), device-type behavior changes, shared daemon code consolidation, automated updates, or MCU changes.

Camera on Debian: new KVS master builds run only on Alpine hosts; Debian boards stay pinned to the last Debian-built KVS master release until reimaged to Alpine. This is an accepted, documented outcome of the transition, not a defect to fix within this milestone.

## Implementation tasks

- `TASK-23.1` - Static musl toolchain is proven for the board stack
- `TASK-23.2` - unit board daemons build as Alpine musl binaries
- `TASK-23.3` - cyberbrick board binaries align to the static-musl policy
- `TASK-23.4` - unit release pipeline publishes Alpine artifacts
- `TASK-23.5` - board artifacts run on both Debian and Alpine hosts
- `TASK-23.6` - board docs reflect the Alpine musl build contract
- `TASK-23.7` - board musl artifacts are validated on physical hardware

## Acceptance summary

The milestone is complete when no CI or justfile build path uses Debian containers or Raspberry Pi apt repositories; all unit and cyberbrick board binaries build in the single pinned Alpine image with CI-enforced linkage assertions (static daemon and hardware worker, musl-dynamic KVS master with asserted stock-Alpine libcamera sonames); cross-distro smoke proves the daemon and hardware worker execute in both `debian:trixie` and pinned Alpine containers while the KVS master executes on Alpine; documentation describes the new build contract and the Debian transition including the camera freeze; and physical validation confirms the static binaries on a real Debian board and the full stack on a real Alpine board. Artifact names and immutable `unit-v*`/`cyberbrick-v*` tags are unchanged, and the full automated test surface (shared AWS python, release tooling, Go, C++) passes.

## Required references

- Architecture spec: `backlog/docs/architecture/board-musl-static-builds/doc-30 - Board-musl-static-builds-architecture.md`
- Constraints: `backlog/docs/constraints/board-musl-static-builds/doc-32 - Constraints-board-musl-static-builds.md` (supersedes the musl-dynamic-only ABI clause of doc-29)
- Parent milestone task: `TASK-23` (milestone `m-4`; note the archived rig milestone task in `backlog/archive/tasks/` also carries the id task-23)
- Alpine reference implementation: `.github/workflows/release-cyberbrick.yml`, `devices/cyberbrick/daemon/justfile`, `release/scripts/assert-board-musl.sh` (generalized from the cyberbrick-only assert script by TASK-23.4)
- Debian surfaces being retired: `.github/workflows/release-unit.yml`, `devices/unit/daemon/justfile`
- Toolchain proof precedent: `backlog/tasks/task-22.1 - Alpine-musl-toolchain-is-proven-for-the-cyberbrick-board-stack.md` and `backlog/docs/architecture/cyberbrick-device-type/doc-27 - Cyberbrick-device-type-architecture.md`
