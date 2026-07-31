---
id: TASK-23.6
title: board docs reflect the Alpine musl build contract
status: Done
assignee: []
created_date: '2026-07-21 09:01'
updated_date: '2026-07-21 20:07'
labels: []
milestone: m-4
dependencies:
  - TASK-23.3
  - TASK-23.4
references:
  - docs/components/board.md
  - docs/artifacts.md
  - docs/components/cyberbrick-board.md
  - docs/installation.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
  - >-
    backlog/docs/constraints/board-musl-static-builds/doc-32 -
    Constraints-board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 62000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Update board documentation for the Alpine build contract and the Debian transition: unit's runbook drops Debian-build and libcamera 0.7 expectations for new artifacts, documents the static daemon and hardware worker linkage checks, and states that camera updates are Alpine-only with Debian boards pinned to the last Debian-built KVS master until reimaged to Alpine.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 docs/components/board.md documents the new artifact ABI (static daemon and hardware worker; Alpine-only musl-dynamic KVS master), replaces the libcamera 0.7 ldd checks accordingly, and adds transition guidance for existing Debian boards including the camera freeze.
- [x] #2 docs/artifacts.md and docs/installation.md describe the unified Alpine build contract for unit and cyberbrick artifacts.
- [x] #3 docs/components/cyberbrick-board.md linkage guidance matches the static daemon and hardware worker policy.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. board.md: replace the Raspberry Pi OS Trixie build story with the Alpine contract (static daemon/hardware worker run on both distros; KVS master Alpine-only), scope libcamera 0.7 ldd checks to the frozen Debian-built camera, document 'not a dynamic executable' as the healthy static state, split maintenance so Debian boards upgrade only the static pair, and refresh the local-dev recipe list (alpine recipes + docker-build + docker-smoke).
2. artifacts.md: unified Alpine build contract paragraph (shared assert script + cross-distro smoke gates), unit asset ABI paragraph with the Debian camera freeze, cyberbrick ldd policy scoped per linkage kind.
3. installation.md: board host and cyberbrick board host ABI summaries updated.
4. cyberbrick-board.md: intro/divergence/constraint bullets, install ldd checks, maintenance coupling, and local-dev verification text aligned to the static policy.
5. development.md: retired trixie recipes replaced with the alpine/docker-build/docker-smoke list.
6. Update stale doc-content test assertions; full suite green.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
docs/components/board.md now states the unit artifact ABI (static daemon + hardware worker run unchanged on Raspberry Pi OS and Alpine; musl-dynamic KVS master is Alpine-only), scopes the libcamera.so.0.7 ldd checks to the frozen last Debian-built KVS master, documents 'not a dynamic executable'/'statically linked' as the healthy static state, adds transition guidance (Debian boards upgrade only txing-unit-daemon + txing-unit-hardware-worker; camera frozen until reimage to Alpine), and lists the alpine build recipes plus docker-build/docker-smoke with the linkage gates they enforce.

docs/artifacts.md describes the unified pinned-Alpine contract for unit and cyberbrick (static pairs + Alpine-only musl-dynamic KVS masters, verified by release/scripts/assert-board-musl.sh and the pre-publish cross-distro smoke), the unit Debian camera freeze, and the cyberbrick ldd policy per linkage kind. docs/installation.md board host and cyberbrick board host sections carry matching ABI summaries. docs/components/cyberbrick-board.md intro, divergence statement, constraint bullets, install-time ldd checks, maintenance coupling (apk/mise move together because of the camera; static pair kernel-only), and local-dev verification text all match the static policy. docs/development.md's retired kvs-build-trixie/hardware-build-trixie references replaced with the alpine/docker-build/docker-smoke recipes.

Stale doc-content test assertions updated (Trixie/libcamera-0.2/0.4 expectations replaced by static-contract and camera-freeze assertions; maintenance upgrade command now asserts the static pair only). Full python suite green: 143 passed, 8 subtests.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
All four board docs now describe the Alpine musl build contract: unit's runbook documents the static daemon/hardware worker checks and the Debian camera freeze with reimage-to-Alpine transition guidance, artifacts.md and installation.md describe the unified pinned-Alpine contract for both devices including the assert-script and cross-distro smoke gates, and cyberbrick-board.md linkage guidance matches the static policy. development.md's stale trixie recipes were also replaced, doc-content test assertions updated, and the full suite passes.
<!-- SECTION:FINAL_SUMMARY:END -->
