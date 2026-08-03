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

- Architecture spec: [Board musl static builds architecture](../architecture/doc-30%20-%20Board-musl-static-builds-architecture.md)
- Constraints: [Board musl static builds constraints](../constraints/doc-32%20-%20Constraints-board-musl-static-builds.md) (supersedes the musl-dynamic-only ABI clause of doc-29)
- Parent tracking issue: [#75 — TASK-23](https://github.com/mparkachov/txing/issues/75). The separate rig tracking issue that reused `TASK-23` is [#76](https://github.com/mparkachov/txing/issues/76).
- Alpine reference implementation: `.github/workflows/release-cyberbrick.yml`, `devices/cyberbrick/daemon/justfile`, `release/scripts/assert-board-musl.sh` (generalized from the cyberbrick-only assert script by TASK-23.4)
- Debian surfaces being retired: `.github/workflows/release-unit.yml`, `devices/unit/daemon/justfile`
- Toolchain proof precedent: [#62 — TASK-22.1](https://github.com/mparkachov/txing/issues/62) and the [Cyberbrick device type architecture](../architecture/doc-27%20-%20Cyberbrick-device-type-architecture.md)

## GitHub issue references

- [#75 — Milestone: Board musl static builds](https://github.com/mparkachov/txing/issues/75) (migrated from `TASK-23`)
- [#79 — one Alpine board runbook covers both device types](https://github.com/mparkachov/txing/issues/79) (migrated from `TASK-23.10`)
- [#80 — board cards are generated from a board config file](https://github.com/mparkachov/txing/issues/80) (migrated from `TASK-23.11`)
- [#81 — a freshly imaged card brings the board up to a reachable base OS](https://github.com/mparkachov/txing/issues/81) (migrated from `TASK-23.12`)
- [#82 — unattended board provisioning is validated on physical hardware](https://github.com/mparkachov/txing/issues/82) (migrated from `TASK-23.13`)
- [#89 — board artifacts run on both Debian and Alpine hosts](https://github.com/mparkachov/txing/issues/89) (migrated from `TASK-23.5`)
- [#90 — board docs reflect the Alpine musl build contract](https://github.com/mparkachov/txing/issues/90) (migrated from `TASK-23.6`)
- [#91 — board musl artifacts are validated on physical hardware](https://github.com/mparkachov/txing/issues/91) (migrated from `TASK-23.7`)
- [#92 — board components build from one shared implementation](https://github.com/mparkachov/txing/issues/92) (migrated from `TASK-23.8`)
- [#93 — board video bridge speaks one protocol package](https://github.com/mparkachov/txing/issues/93) (migrated from `TASK-23.9`)
