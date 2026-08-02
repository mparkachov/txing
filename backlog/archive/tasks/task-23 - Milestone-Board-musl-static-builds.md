---
id: TASK-23
title: 'Milestone: Board musl static builds'
status: Done
assignee: []
created_date: '2026-07-21 09:00'
updated_date: '2026-07-31 20:48'
labels: []
milestone: m-4
dependencies: []
references:
  - .github/workflows/release-unit.yml
  - devices/unit/daemon/justfile
  - devices/cyberbrick/daemon/justfile
  - release/scripts/assert-cyberbrick-musl.sh
  - docs/components/board.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
priority: high
ordinal: 56000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Complete the migration of board component builds off Debian: instead of debian:trixie containers with Raspberry Pi apt repositories, all unit and cyberbrick board binaries build in the single pinned Alpine/musl toolchain, statically linked wherever possible so the shipped daemon and hardware worker run unmodified on both existing Debian boards and Alpine boards during the transition off Debian. The camera KVS master cannot be linked statically and stays musl-dynamic against stock Alpine libcamera, making new camera builds Alpine-only; Debian boards keep the last Debian-built KVS master until reimaged to Alpine. Implementation must proceed through child tasks and must not run AWS mutation commands; physical-board steps are prepared for the operator to run manually.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Board musl migration is split into scoped child tasks covering static toolchain validation, unit and cyberbrick Alpine builds, the unit release pipeline, cross-distro runtime verification, documentation, and physical-hardware validation.
- [x] #2 After migration no CI or justfile build path uses Debian containers or Raspberry Pi apt repositories; all board binaries build in the single pinned Alpine image with CI-asserted linkage kinds (static daemon and hardware worker; musl-dynamic KVS master).
- [x] #3 Existing device behavior is unchanged until the respective child task lands; completion evidence includes automated linkage assertions, cross-distro smoke runs in debian:trixie and pinned Alpine containers, and documented physical validation on a Debian and an Alpine board.
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Milestone: board musl static builds, complete.

Thirteen child tasks, all Done: static musl toolchain validation, unit and
cyberbrick Alpine builds, both release pipelines, cross-distro runtime
verification, documentation, the consolidation onto one shared board
implementation and one protocol package, a single Alpine runbook, the unattended
card, and physical-hardware validation.

No CI or justfile path builds board binaries in Debian containers or from
Raspberry Pi apt repositories. Everything builds in the single pinned Alpine
image, with linkage kinds asserted in CI: static daemon and hardware worker with
no ELF interpreter, musl-dynamic KVS master resolving the expected libcamera
sonames, plus cross-distro smoke runs in debian:trixie and pinned Alpine.

Physical validation covers both userlands. TASK-23.7 recorded a Debian board
running the static pair alongside the pinned Debian-built KVS master, and an
Alpine board running the full musl stack. TASK-23.13 then took a unit board from a
blank card to REDCON 1 with live video and motion control on Alpine 3.24.1 under a
read-only root across a cold boot, validating the unattended installer, the
unified protocol and the consolidated runbook together.
<!-- SECTION:FINAL_SUMMARY:END -->
