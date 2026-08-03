---
id: doc-28
title: 'Milestone: Cyberbrick device type'
type: specification
created_date: '2026-07-15 07:33'
updated_date: '2026-07-15 07:39'
tags:
  - cyberbrick
  - device-type
  - milestone
---
# Milestone: Cyberbrick device type

## Goal

Introduce `cyberbrick` as a first-class txing device type with unit-parity functionality — same daemons, REDCON ladder, shadows, video, and office behavior — whose board stack runs on Alpine Linux: aarch64 binaries dynamically linked against musl, OpenRC-managed services, read-only root, and unit's manual install/update workflow.

## Scope

This milestone covers the Alpine/musl toolchain validation spike, the device catalog/UI contract (manifest, shadow schemas, AWS type catalog, certificate bundle, office adapter), the copied-and-renamed `devices/cyberbrick` board stack (Go daemon, KVS master, hardware worker, protos) with Alpine build recipes and musl-dynamic assertions, the `cyberbrick-v` release pipeline and version tooling, the Alpine board runbook (fresh install, OpenRC, read-only root, maintenance), and hardware bring-up to unit parity on a Raspberry Pi Zero 2 W.

This milestone does not cover a cyberbrick MCU (the watch layer stays unit's Zephyr firmware), behavior changes relative to unit beyond the OS/ABI/init swap, changes to unit/rig/office internals, shared daemon code consolidation, or automated updates.

Video on Alpine carries known kernel/library risk; the spike task sets the expectation, and a documented degraded-video state on hardware is an acceptable milestone outcome if streaming is blocked by the Alpine kernel, with a follow-up task filed.

## Implementation tasks

- `TASK-22.1` - Alpine musl toolchain is proven for the cyberbrick board stack
- `TASK-22.2` - cyberbrick catalog and UI contract is first-class
- `TASK-22.3` - cyberbrick board daemons build as musl-dynamic Alpine binaries
- `TASK-22.4` - cyberbrick release pipeline publishes Alpine artifacts
- `TASK-22.5` - cyberbrick Alpine board runbook is complete
- `TASK-22.6` - cyberbrick board reaches unit parity on hardware

## Acceptance summary

The milestone is complete when a cyberbrick board installed from the documented Alpine runbook registers through the standard AWS flow, is born under a raspi rig, converges the full REDCON ladder from office with correct command feedback, drives motors and answers MCP at parity with unit, meets the documented video expectation from the spike, and survives read-only-root reboots with OpenRC autostarting the daemons offline. All three shipped binaries are dynamically linked against musl with CI-enforced assertions, releases are published under immutable `cyberbrick-v*` tags, and the full automated test surface (shared AWS python, release tooling, office, Go, C++) passes with existing device types unchanged.

## Required references

- Architecture spec: [Cyberbrick device type architecture](../architecture/doc-27%20-%20Cyberbrick-device-type-architecture.md)
- Constraints: [Cyberbrick Alpine board constraints](../constraints/doc-29%20-%20Constraints-cyberbrick-Alpine-board.md)
- Parent tracking issue: [#60 — TASK-22](https://github.com/mparkachov/txing/issues/60). The separate Mac tracking issue that reused `TASK-22` is [#61](https://github.com/mparkachov/txing/issues/61).
- Unit board runbook (structural template): `docs/components/board.md`
- Unit build/release surfaces: `devices/unit/daemon/justfile`, `.github/workflows/release-unit.yml`
- Device type precedent: [Mac device type architecture](../architecture/doc-23%20-%20Mac-device-type-architecture.md)

## GitHub issue references

- [#60 — Milestone: Cyberbrick device type](https://github.com/mparkachov/txing/issues/60) (migrated from `TASK-22`)
