---
id: TASK-22.4
title: cyberbrick release pipeline publishes Alpine artifacts
status: Done
assignee:
  - '@codex'
created_date: '2026-07-15 07:37'
updated_date: '2026-08-02 12:55'
labels: []
milestone: m-3
dependencies: []
references:
  - .github/workflows/release-unit.yml
  - release/src/txing_release/cli.py
  - release/justfile
documentation:
  - docs/artifacts.md
  - docs/development.md
modified_files:
  - .github/workflows/release-cyberbrick.yml
  - devices/cyberbrick/board/hardware_worker/CMakeLists.txt
  - devices/cyberbrick/board/kvs_master/CMakeLists.txt
  - devices/cyberbrick/board/kvs_master/include/kvs_master/version.hpp
  - docs/artifacts.md
  - docs/development.md
  - release/justfile
  - release/scripts/assert-cyberbrick-musl.sh
  - release/src/txing_release/cli.py
  - release/tests/test_cli.py
  - release/versions/cyberbrick
  - shared/aws/python/tests/test_versioning.py
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
- [x] #1 A manually dispatched release workflow publishes an immutable cyberbrick-v tagged release with three txing-cyberbrick-*-linux-aarch64.tar.gz assets, each containing exactly one root-level executable built in the pinned Alpine container.
- [x] #2 CI enforces the musl-dynamic contract on every published binary: musl interpreter present, all shared libraries resolved, and the expected libcamera linkage for the KVS master.
- [x] #3 Release tooling (bump, print, build) covers the cyberbrick component with its own version file and version surfaces, and release tooling tests pass.
- [x] #4 Versioning and policy tests assert the cyberbrick workflow invariants without weakening existing component assertions.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add release/versions/cyberbrick and register the component in the release CLI and release justfile so bump, print, and build manage the Cyberbrick Go, KVS, and hardware version surfaces and dispatch release-cyberbrick.yml; keep publish unsupported because board updates remain manual.
2. Add .github/workflows/release-cyberbrick.yml using manual workflow_dispatch, immutable cyberbrick-v metadata checks, native ubuntu-24.04-arm jobs running docker.io/library/alpine:3.23.5 containers, one build, test, and package matrix entry per daemon, exact single-root tar assertions, and post-strip musl interpreter and resolved-library checks including libcamera 0.6 for KVS.
3. Extend release CLI tests and repository versioning and policy tests with Cyberbrick-specific assertions while retaining every existing rig, Lambda, and unit assertion; update artifact and development documentation for the new channel and its dynamic-musl compatibility boundary.
4. Validate release CLI bump, print, and package tests, the full shared AWS versioning suite, just recipe routing and POSIX syntax, workflow YAML and policy invariants, and a local pinned-Alpine build and package drill that proves all three archive shapes and final binary link contracts. Do not dispatch GitHub Actions, create a tag or release, deploy, or update a board.
5. Audit each acceptance criterion against current files and command evidence, confirm existing workflows and unit device sources remain unchanged except the scoped release integrations, record results in TASK-22.4, and mark Done only when all four criteria are proven.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented a manually dispatched immutable cyberbrick-v release workflow with a three-entry build matrix for txing-cyberbrick-daemon, txing-cyberbrick-kvs-master, and txing-cyberbrick-hardware-worker. Each entry builds and tests in docker.io/library/alpine:3.23.5 on native arm64, injects release/versions/cyberbrick version 0.15.4, checks the emitted --version value, strips the packaged executable, validates the ARM64 musl interpreter and complete ldd resolution, and creates one exact root-level executable archive. KVS additionally requires libcamera.so.0.6 and libcamera-base.so.0.6. The publish job accepts only the three named assets and preserves the component-prefixed monotonic and immutable release gates.

Registered cyberbrick in release bump, print, and build routing. Added CMake release-version overrides for both C++ workers and a macro fallback for the KVS version header. Updated release CLI fixtures and policy/versioning assertions without adding Cyberbrick to the existing Debian/Go assertions for rig, Lambda, and unit. Updated artifact and development documentation with the Cyberbrick release stream, Alpine/musl compatibility boundary, manual writable-root rollout, and physical-board validation boundary.

Validation passed: aggregate native-arm64 Alpine 3.23.5 build; container Go tests; KVS CTest 1/1; hardware-worker CTest 2/2; host Cyberbrick Go tests; host KVS CTest 1/1; host hardware-worker CTest 1/1; exact post-strip musl/ldd/libcamera package checks; three single-root tar archives; 7 release CLI tests; 20 shared versioning/policy tests; release sdist and wheel build; same-version cyberbrick bump audit; release build dry-run routing; workflow YAML and embedded sh/bash syntax; ShellCheck; Python compileall; git diff --check. Existing rig, Lambda, and unit release workflows and devices/unit remain unchanged. No GitHub workflow was dispatched and no tag, release, AWS mutation, deployment, or board operation was performed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added and fully validated the Cyberbrick Alpine release channel. Manual release dispatch now builds, tests, musl-audits, packages, and immutably publishes exactly three cyberbrick-v arm64 assets. Release tooling owns all Cyberbrick version surfaces, regression tests preserve existing component policy, and operator docs describe the coupled Alpine/runtime rollout boundary. All automated and local pinned-container checks pass; publishing and physical-board rollout remain explicit manual actions.
<!-- SECTION:FINAL_SUMMARY:END -->
