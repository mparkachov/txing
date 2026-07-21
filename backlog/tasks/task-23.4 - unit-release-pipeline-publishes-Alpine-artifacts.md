---
id: TASK-23.4
title: unit release pipeline publishes Alpine artifacts
status: To Do
assignee: []
created_date: '2026-07-21 09:01'
labels: []
milestone: m-4
dependencies:
  - TASK-23.2
references:
  - .github/workflows/release-unit.yml
  - release/scripts/assert-cyberbrick-musl.sh
  - shared/aws/python/tests/test_versioning.py
documentation:
  - >-
    backlog/docs/architecture/board-musl-static-builds/doc-30 -
    Board-musl-static-builds-architecture.md
  - >-
    backlog/docs/constraints/board-musl-static-builds/doc-32 -
    Constraints-board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 60000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Rewrite .github/workflows/release-unit.yml to build all three unit board binaries in the pinned alpine:3.23.5 container via a component matrix like release-cyberbrick.yml, dropping the debian:trixie jobs, the Raspberry Pi apt repository, and the libcamera 0.7 assertions. The musl assert script generalizes into a shared board script parameterized by linkage kind (static, or musl-dynamic plus libcamera) used by both workflows. Artifact names and the unit-v tag flow are unchanged.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 release-unit.yml builds the unit daemon, KVS master, and hardware worker in the pinned alpine:3.23.5 container with apk-only dependencies; no debian:trixie container, raspi apt source, or libcamera 0.7 assertion remains.
- [ ] #2 A shared assert script generalized from release/scripts/assert-cyberbrick-musl.sh enforces static linkage for the daemon and hardware worker and musl-dynamic plus stock Alpine libcamera sonames for the KVS master, and both unit and cyberbrick workflows call it.
- [ ] #3 Published assets keep their existing names (txing-unit-*-linux-aarch64.tar.gz, stripped single-root-entry tarballs) under immutable unit-v* tags.
- [ ] #4 The unit workflow-text assertions in shared/aws/python/tests/test_versioning.py are updated and the suite passes.
<!-- AC:END -->
