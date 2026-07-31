---
id: TASK-23.4
title: unit release pipeline publishes Alpine artifacts
status: Done
assignee: []
created_date: '2026-07-21 09:01'
updated_date: '2026-07-21 19:53'
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
- [x] #1 release-unit.yml builds the unit daemon, KVS master, and hardware worker in the pinned alpine:3.23.5 container with apk-only dependencies; no debian:trixie container, raspi apt source, or libcamera 0.7 assertion remains.
- [x] #2 A shared assert script generalized from release/scripts/assert-cyberbrick-musl.sh enforces static linkage for the daemon and hardware worker and musl-dynamic plus stock Alpine libcamera sonames for the KVS master, and both unit and cyberbrick workflows call it.
- [x] #3 Published assets keep their existing names (txing-unit-*-linux-aarch64.tar.gz, stripped single-root-entry tarballs) under immutable unit-v* tags.
- [x] #4 The unit workflow-text assertions in shared/aws/python/tests/test_versioning.py are updated and the suite passes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Generalize assert-cyberbrick-musl.sh into release/scripts/assert-board-musl.sh with linkage kinds static|musl-libcamera; delete the old script; point release-cyberbrick.yml matrix kinds and call site at it.
2. Rewrite release-unit.yml as a cyberbrick-style component matrix on pinned alpine:3.23.5: static CGO_ENABLED=0 daemon with version ldflags, musl-dynamic kvs-master (Starfield CA path, SDK commit pin, ctest), static hardware worker via release/scripts/build-board-static-toolchain.sh; version-equality gate; strip + shared assert + single-root tarball packaging; metadata/publish jobs unchanged.
3. Update test_versioning.py: unit workflow block flipped to Alpine assertions, unit dropped from the apt-Go workflow loop, assert-script variable renamed, kind assertions added.
4. Update doc-29/doc-31 script references.
5. Verify: yaml/sh syntax, pytest, assert script positive+negative runs against real unit and cyberbrick artifacts, stripped-binary assert.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
release-unit.yml rewritten onto the pinned alpine:3.23.5 container as a component matrix mirroring release-cyberbrick.yml: apk-only dependencies (same union as cyberbrick incl. curl/openssl-libs-static/zlib-static), static CGO_ENABLED=0 daemon with DaemonVersion ldflags injection, kvs-master musl-dynamic with BUILD_TESTING=ON + ctest and the Starfield CA default, hardware worker fully static via the shared release/scripts/build-board-static-toolchain.sh, and a --version == 'binary version' gate for all three. debian:trixie containers, the raspi apt source, apt-get, and the libcamera 0.7 assertions are gone (enforced by assertNotIn tests). Metadata and publish jobs are unchanged, so asset names (txing-unit-*-linux-aarch64.tar.gz), stripped single-root-entry tarballs, and the immutable unit-v* tag flow are preserved.

assert-cyberbrick-musl.sh replaced by release/scripts/assert-board-musl.sh parameterized by linkage kind (static | musl-libcamera); release-cyberbrick.yml matrix kinds updated to the linkage names and both workflows call the shared script; doc-29/doc-31 references updated.

Evidence: yaml + sh syntax checks pass; test_versioning.py 21 passed + 8 subtests (unit removed from the apt-Go workflow loop; unit block asserts the Alpine pin, toolchain script, static link flags, shared assert script, and both kinds); assert-board-musl.sh ran green against all six locally built unit and cyberbrick binaries in a stock-Alpine container, rejected wrong-kind and unknown-kind invocations, and passed on a stripped static-pie hardware worker which still executed --version 0.15.4.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
release-unit.yml now builds all three unit board binaries in the pinned alpine:3.23.5 container via a component matrix (static daemon and hardware worker, musl-dynamic kvs-master), with the Debian/raspi path fully removed and asset names plus the immutable unit-v tag flow unchanged. The new shared release/scripts/assert-board-musl.sh (kinds static | musl-libcamera) replaces assert-cyberbrick-musl.sh and is called by both board workflows. Updated test assertions pass; the script was validated positively and negatively against real artifacts of both devices.
<!-- SECTION:FINAL_SUMMARY:END -->
