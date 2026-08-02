---
id: TASK-23.10
title: one Alpine board runbook covers both device types
status: Done
assignee:
  - '@claude'
created_date: '2026-07-25 17:43'
updated_date: '2026-08-02 12:55'
labels: []
milestone: m-4
dependencies: []
references:
  - docs/components/board.md
  - docs/components/cyberbrick-board.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 66000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Board documentation is split by accident of history rather than by content: the unit runbook is Debian and systemd, the cyberbrick runbook is Alpine and OpenRC, and the two duplicate most of their install and maintenance steps while differing only in names and OS commands. Unit on Alpine is therefore undocumented. Consolidate into one Alpine runbook covering both device types, and freeze the Debian material for the boards not yet reimaged. Note that the unit runbook also holds the device-agnostic board behavior contract that the cyberbrick runbook delegates to, so the split is by content, not by file.

Freezing Debian is now settled policy rather than an open question: `docs/constraints/board-os-alpine-only.md` records that boards run Alpine only, that Debian receives no further investment, and that a Debian board is reimaged rather than upgraded. The consolidation carries that framing rather than restating the reasoning.

The consolidation also has to close a command-surface divergence introduced while merging the implementation. TASK-23.8 collapsed the two per-device daemon justfiles into one shared module, which moved board commands from `just <device>::daemon::<recipe>` to `just common::board::<recipe> <device>`. That is a second invocation grammar for an operator concept the repository already had: `devices/common/mcu` shares a stack across four device types and, per `doc-7 - Constraints-MCU-stock-Zephyr-shared-stack`, keeps device-scoped commands device-owned (`just <device>::mcu::build`, `just <device>::mcu::flash`) while only genuinely device-independent operations are common-owned (`just mcu::check`). Board should follow the same rule, so that a device-scoped board operation reads the same as a device-scoped MCU operation and a new device type gains a board component the same way it gains an MCU target. The shared implementation under `devices/common/board` does not change; only the entry points and the documentation that names them.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A single board runbook covers fresh install, maintenance, and troubleshooting for both device types on Alpine, with device-specific values collected in one place rather than spread through the prose.
- [x] #2 The device-agnostic board behavior contract remains available and the device documents that delegate to it still resolve.
- [x] #3 Debian and systemd install and maintenance instructions remain available as clearly frozen material and are no longer presented as current practice, consistent with the recorded Alpine-only board OS decision.
- [x] #4 Device-scoped board operations are invoked device-owned as `just <device>::board::<recipe>`, matching how device-scoped MCU operations are invoked, while genuinely device-independent board operations stay common-owned with no device argument.
- [x] #5 Adding a board component to a new device type needs only its per-device material and the device-owned entry point, with no change to the shared implementation.
- [x] #6 The documentation index and all cross-references resolve, every documented board command matches the entry points that exist, and documentation tests reflect the new structure.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Command-surface reconciliation (AC #4 and #5). The shared implementation under
`devices/common/board` does not move; only the entry points and the docs that
name them.

Rule to apply, taken from `doc-7 - Constraints-MCU-stock-Zephyr-shared-stack`:
a device-scoped operation is device-owned, a device-independent operation is
common-owned. Applied to the board module:

- Device-owned, one thin module per device type, mirroring the existing
  `mod mcu 'mcu/justfile'` line in each device justfile: `role-policy`, `test`,
  `run`, `kvs-build-native`, `kvs-test-native`, `hardware-build-native`,
  `hardware-test-native`, `daemon-build-alpine`, `kvs-build-alpine`,
  `hardware-build-alpine`, `docker-build`, `docker-smoke`, `clean`. Each
  delegates into the shared recipe with the device pre-bound, so
  `just unit::board::docker-build` reads like `just unit::mcu::build`.
- Common-owned, unchanged: `proto-gen`, which takes no device argument since
  TASK-23.9 unified the protocol, and is the board counterpart to `mcu::check`.

Mechanical scope, from a sweep of current `common::board::` call sites:

- `docs/components/board.md` 13, `docs/development.md` 12,
  `docs/components/cyberbrick-board.md` 10 - most of these collapse into the
  consolidated runbook this task produces anyway, so the rewrite lands with the
  consolidation rather than as a separate pass.
- `shared/aws/python/tests/test_versioning.py` 4, `devices/common/board/README.md` 4,
  `devices/common/board/justfile` 4 (internal self-references),
  `docs/constraints/repository-rules.md` 2, `docs/aws.md` 1,
  `devices/mac/justfile` 1 (an error message pointing operators at the board
  recipe).

Two details worth not rediscovering:

- The shared justfile validates its device argument in `_require-device` against
  `devices/<device>/manifest.toml` and `release/versions/<device>`. Device-owned
  wrappers should keep that check reachable rather than bypassing it, so a
  half-registered device type still fails early.
- Per-device build and output directories are already device-suffixed
  (`build-<device>`, `build-tests-<device>`, `target/docker-build-<device>`), so
  device-owned entry points need no change there and the two device types still
  cannot collide.

AC #5 is the test of whether this landed: adding a board component to a new
device type should need its `manifest.toml`, its `aws/` and `web/` material, a
`release/versions/<device>` stream, and one `mod board` line, with nothing added
under `devices/common/board`.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`docs/components/board.md` is now the single Alpine runbook for both device
types, and `docs/components/cyberbrick-board.md` is gone. The Debian and systemd
install and maintenance steps moved to `docs/components/board-debian-frozen.md`
under a banner that states they are frozen, that the old local gRPC packages are
wire-incompatible with the current ones, and that such a board is reimaged rather
than upgraded.

The runbook opens with a Device Types table holding every value that differs
between device types - binary names, config directory, hardware socket, adapter
id, release version file and tag prefix, manifest, shadow directory - and the
body uses `<device>` throughout. The device-agnostic behaviour contract
(Responsibilities, REDCON Contract, Retained AWS IoT Topics, Runtime Interfaces,
Runtime Configuration) stays in this document, so the contracts and component
docs that delegate to it still resolve. A new Local Protocol Contracts section
names the two device-independent gRPC packages and links their contract docs.

Command surface, closing the divergence recorded when this task was written.
Device-scoped board operations are now device-owned and read like the MCU ones:

  just unit::board::docker-build        just unit::mcu::build
  just cyberbrick::board::docker-smoke  just power-si::mcu::flash

Each device type carries a five-line `board.just` that binds `device` and the
shared justfile path and imports `devices/common/board/device-recipes.just`,
which holds the thirteen delegating recipes once. `just` module scope makes the
imported recipes see the importing file's variables, so the per-device file
stays a declaration rather than a copy. Delegation routes through the shared
recipes, so `_require-device` still validates the device against its manifest
and release stream: `just common::board::docker-build bogus` still fails with
"unknown board device type". `proto-gen` stays common-owned with no device
argument, the board counterpart to `mcu::check`.

Verified rather than asserted:

- A sweep of every relative markdown link across `docs/`, `AGENTS.md`, and
  `devices/common/board/README.md` resolves; no reference to the removed
  cyberbrick runbook survives.
- Every board command named in the documentation is backed by a recipe that
  exists. This caught `just common::board::cert`, which named a recipe that
  never existed - a stale example in `repository-rules.md` that TASK-23.9's
  rewrite had propagated. It now uses `role-policy`, which really does take the
  positional argument the rule is illustrating.
- No file under `devices/common/board` names a specific device type, so adding a
  board component to a new device needs only its per-device material and a
  five-line entry point.

The consolidation also recovered content the merge would otherwise have dropped:
the forward-only release-model note existed only in the unit runbook's Release
Artifacts section, which the cyberbrick version did not carry. The documentation
tests caught it.

Test fallout. Two suites predate the split and asserted against a single
`board.md`; they now read the board documentation as a whole, because their
intent is that content survived rather than which file holds it, and placement
is covered by the consolidation assertions. The former cyberbrick runbook test
became `test_board_runbook_describes_alpine_openrc_for_both_device_types`, and
its `assertNotIn("txing-unit-daemon", ...)` inverted: the unified runbook lists
both device types in its table by design, so it now asserts both appear there,
that the removed runbook is gone, and that no `just <device>::daemon::` command
name comes back.

Final state: shared/aws/python 147 passed, release/tests 7 passed, hardware
worker ctest green for both device types through the new device-owned recipes.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
One Alpine runbook now covers both board device types, with every differing value collected in a Device Types table and the body written against <device>. The Debian and systemd material moved to a clearly frozen document that states those boards cannot reach the current protocol and must be reimaged, and the device-agnostic behaviour contract stayed put so delegating documents still resolve. Board commands also stopped being a special case: device-scoped operations are device-owned as just <device>::board::<recipe>, matching the MCU precedent in doc-7, via a five-line per-device entry point that imports thirteen delegating recipes shared once, while proto-gen stays common-owned as the board counterpart to mcu::check. Verified by resolving every relative documentation link, checking every documented board command against a recipe that exists, and confirming no file under devices/common/board names a device type.
<!-- SECTION:FINAL_SUMMARY:END -->
