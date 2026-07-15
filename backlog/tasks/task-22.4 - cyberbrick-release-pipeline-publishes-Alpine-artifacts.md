---
id: TASK-22.4
title: cyberbrick release pipeline publishes Alpine artifacts
status: To Do
assignee: []
created_date: '2026-07-15 07:37'
labels: []
milestone: m-3
dependencies:
  - TASK-22.3
references:
  - .github/workflows/release-unit.yml
  - release/src/txing_release/cli.py
  - release/justfile
documentation:
  - >-
    backlog/docs/architecture/cyberbrick-device-type/doc-27 -
    Cyberbrick-device-type-architecture.md
  - >-
    backlog/docs/constraints/cyberbrick-alpine-board/doc-29 -
    Constraints-cyberbrick-Alpine-board.md
parent_task_id: TASK-22
priority: medium
ordinal: 53000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Cyberbrick has its own component release path matching unit's operational model: manual dispatch, immutable cyberbrick-v tags, one tar.gz asset per daemon with exactly one root-level executable, built in the pinned Alpine container with musl-dynamic assertions enforced in CI. Version bump tooling covers cyberbrick's version surfaces.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A manually dispatched release workflow publishes an immutable cyberbrick-v tagged release with three txing-cyberbrick-*-linux-aarch64.tar.gz assets, each containing exactly one root-level executable built in the pinned Alpine container.
- [ ] #2 CI enforces the musl-dynamic contract on every published binary: musl interpreter present, all shared libraries resolved, and the expected libcamera linkage for the KVS master.
- [ ] #3 Release tooling (bump, print, build) covers the cyberbrick component with its own version file and version surfaces, and release tooling tests pass.
- [ ] #4 Versioning and policy tests assert the cyberbrick workflow invariants without weakening existing component assertions.
<!-- AC:END -->
