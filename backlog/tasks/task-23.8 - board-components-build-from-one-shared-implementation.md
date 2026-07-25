---
id: TASK-23.8
title: board components build from one shared implementation
status: To Do
assignee: []
created_date: '2026-07-25 17:43'
updated_date: '2026-07-25 17:44'
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
- [ ] #1 Both device types build their daemon, hardware worker, and KVS master from a single shared source tree, with device differences supplied by a per-device profile rather than duplicated sources.
- [ ] #2 The signaling trust anchor is selectable at runtime on both device types, so a board can point the TLS layer at a single-anchor file without rebuilding.
- [ ] #3 Release version strings are injected at build time for both device types, and each device keeps its own independent release stream and version prefix.
- [ ] #4 Existing linkage and cross-distro gates pass for both device types built from the merged sources.
- [ ] #5 Device shadow schemas and manifests that encode genuine device differences remain per-device.
- [ ] #6 Build and release tooling converges on the better of the two existing implementations in each direction, rather than one device's tooling simply replacing the other's.
<!-- AC:END -->
