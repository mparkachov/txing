---
id: TASK-23.5
title: board artifacts run on both Debian and Alpine hosts
status: Done
assignee: []
created_date: '2026-07-21 09:01'
updated_date: '2026-08-02 12:55'
labels: []
milestone: m-4
dependencies: []
references:
  - .github/workflows/release-unit.yml
  - .github/workflows/release-cyberbrick.yml
  - devices/unit/daemon/justfile
  - devices/cyberbrick/daemon/justfile
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 61000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Prove the transition promise in CI and locally: the static daemon and hardware worker execute on both Debian and Alpine userlands, and the KVS master executes on Alpine. Both release workflows gain cross-distro smoke steps and the justfiles gain a matching local recipe.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Both release workflows execute each built daemon and hardware worker binary in debian:trixie and pinned alpine:3.23.5 linux/arm64 containers (version or startup smoke) and the KVS master in the Alpine container only, failing the release on any smoke failure.
- [x] #2 A justfile recipe reproduces the same cross-distro smoke locally via docker run for unit and cyberbrick artifacts.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. New shared release/scripts/smoke-board-cross-distro.sh: executes a binary per linkage kind (static -> bare debian:trixie + bare alpine:3.23.5; musl-libcamera -> alpine with the documented runtime package superset), asserting the --version output equals the expected version line; native linux/arm64 docker guard.
2. Both release workflows gain a Cross-distro smoke job between build and publish that downloads the packaged assets, extracts them, and runs the script for all three binaries; publish depends on smoke, so any smoke failure blocks the release.
3. Both daemon justfiles gain a docker-smoke recipe reproducing the same runs against target/docker-build/bin.
4. Test assertions for the script pins, workflow smoke jobs, and justfile recipes.
5. Verify: syntax checks, pytest, real docker-smoke runs for both devices, negative version-mismatch run.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added release/scripts/smoke-board-cross-distro.sh (kind static runs the binary in bare debian:trixie and bare pinned alpine:3.23.5; kind musl-libcamera runs it in Alpine provisioned with the doc'd runtime package superset from the cyberbrick runbook; each run's last output line must equal the expected '<binary> <version>' line; requires a native linux/arm64 docker daemon).

release-unit.yml and release-cyberbrick.yml both gained a 'Cross-distro smoke' job between build and publish: it downloads the packaged release assets, extracts the tarballs, and smokes the daemon + hardware worker on both distros and the KVS master on Alpine only, using the release version from metadata. publish now needs smoke, so a smoke failure fails the release before anything is published.

Both daemon justfiles gained a docker-smoke recipe reproducing the identical runs against target/docker-build/bin (unit reads release/versions/unit; cyberbrick reads packageVersion, matching each justfile's docker-build convention).

Evidence: sh/just/yaml syntax checks green; test_versioning.py 21 passed + 8 subtests with new assertions on the script pins, both workflow smoke jobs, and both justfile recipes; just unit::daemon::docker-smoke and just cyberbrick::daemon::docker-smoke both fully green (10 runs: 2x2 static cross-distro per device + 1 Alpine KVS master per device, all reporting 0.15.4); a wrong expected version makes the script exit non-zero.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Both release workflows now prove the doc-32 transition promise before publishing: a Cross-distro smoke job executes the packaged static daemon and hardware worker in bare debian:trixie and pinned alpine:3.23.5 containers and the musl-dynamic KVS master in provisioned Alpine, via the new shared release/scripts/smoke-board-cross-distro.sh; publish is blocked on smoke success. Matching docker-smoke justfile recipes reproduce the runs locally, verified green for both unit and cyberbrick artifacts.
<!-- SECTION:FINAL_SUMMARY:END -->
