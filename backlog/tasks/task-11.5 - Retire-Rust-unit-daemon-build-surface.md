---
id: TASK-11.5
title: Retire Rust unit daemon build surface
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 14:30'
updated_date: '2026-05-23 16:29'
labels: []
milestone: Go unit board daemon replacement
dependencies:
  - TASK-11.4
references:
  - devices/unit/daemon/Cargo.toml
  - devices/unit/daemon/src/lib.rs
  - devices/unit/daemon/src/main.rs
documentation:
  - >-
    backlog/docs/milestones/go-unit-board-daemon-replacement/doc-2 -
    Milestone-Go-unit-board-daemon-replacement.md
  - >-
    backlog/docs/constraints/unit-board-daemon-go-parity/doc-3 -
    Constraints-unit-board-daemon-Go-parity.md
modified_files:
  - devices/unit/daemon/Cargo.lock
  - devices/unit/daemon/Cargo.toml
  - devices/unit/daemon/Dockerfile.docker-builder
  - devices/unit/daemon/build.rs
  - devices/unit/daemon/justfile
  - devices/unit/daemon/src/lib.rs
  - devices/unit/daemon/src/main.rs
  - devices/unit/docs/board-video.md
  - docs/future-work.md
  - shared/aws/python/tests/test_versioning.py
parent_task_id: TASK-11
ordinal: 16000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Rust daemon source, Cargo files, build.rs, and Rust-specific Docker/release build surfaces are removed or made inactive after Go parity tests pass.
- [x] #2 No active build, release, versioning, or install path depends on Cargo for txing-unit-daemon.
- [x] #3 Search confirms old Rust daemon active references are gone or retained only as explicit historical/migration notes.
- [x] #4 Final validation runs Go daemon tests, KVS native tests, and release/versioning checks relevant to the unit board runtime.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Audit the current unit daemon build/release/install/versioning surfaces and searches for Rust Cargo-based txing-unit-daemon references.\n2. Remove or make inactive any remaining Rust daemon source, Cargo, build.rs, Docker, release, versioning, or install surfaces.\n3. Run Go daemon, KVS native, and release/versioning validation relevant to the unit board runtime.\n4. Mark acceptance criteria complete only after evidence proves no active Rust daemon build path remains, then close TASK-11.5 and the parent milestone if all child work is complete.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Closeout audit removed the tracked Rust unit daemon source/Cargo/build.rs/Docker builder files and removed the Rust Docker helper recipes from the active daemon justfile. Updated active board video docs and future-work notes so current text no longer describes the unit daemon as Rust or tracks the retired unit daemon Cargo.lock. Targeted searches now find old unit daemon Cargo/Rust/Docker paths only in historical Backlog context or negative assertions that prevent reintroduction.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Retired the Rust txing-unit-daemon build surface. Removed devices/unit/daemon/Cargo.toml, Cargo.lock, build.rs, Dockerfile.docker-builder, and src/*.rs; removed the Rust Docker builder recipes/cargo volumes from devices/unit/daemon/justfile; updated docs and release/versioning tests to assert the retired surfaces stay absent. Validation passed: go test ./... in devices/unit/daemon with workspace-local Go caches; injected Go build printed txing-unit-daemon 9.8.7-test; just --justfile devices/unit/daemon/justfile kvs-test-native; python3 release/src/txing_release/cli.py check; python3 -m unittest shared.aws.python.tests.test_versioning; git diff --check; targeted searches for old active Cargo/Rust/Docker unit daemon surfaces.
<!-- SECTION:FINAL_SUMMARY:END -->
