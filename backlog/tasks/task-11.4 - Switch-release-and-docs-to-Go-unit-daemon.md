---
id: TASK-11.4
title: Switch release and docs to Go unit daemon
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 14:30'
updated_date: '2026-05-23 15:53'
labels: []
milestone: Go unit board daemon replacement
dependencies:
  - TASK-11.1
  - TASK-11.2
  - TASK-11.3
references:
  - .github/workflows/release.yml
  - release/src/txing_release/cli.py
  - shared/aws/python/tests/test_versioning.py
documentation:
  - >-
    backlog/docs/architecture/unit-daemon-go-reimplementation/doc-1 -
    Unit-daemon-Go-reimplementation.md
  - >-
    backlog/docs/milestones/go-unit-board-daemon-replacement/doc-2 -
    Milestone-Go-unit-board-daemon-replacement.md
  - >-
    backlog/docs/constraints/unit-board-daemon-go-parity/doc-3 -
    Constraints-unit-board-daemon-Go-parity.md
modified_files:
  - .github/workflows/release.yml
  - devices/unit/board/AGENTS.md
  - devices/unit/daemon/justfile
  - docs/artifacts.md
  - docs/components/board.md
  - docs/components/office.md
  - docs/development.md
  - docs/installation.md
  - release/src/txing_release/cli.py
  - shared/aws/python/tests/test_versioning.py
parent_task_id: TASK-11
ordinal: 15000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Release workflow builds, tests, packages, and publishes the Go txing-unit-daemon asset with version injection and no Cargo unit-daemon job.
- [x] #2 Release workflow packages txing-unit-kvs-master-linux-aarch64.tar.gz and all release notes/checks refer to the new KVS asset name.
- [x] #3 Versioning and documentation tests assert the Go daemon, txing-unit-kvs-master, and txing-unit.target active surfaces.
- [x] #4 Current board, artifacts, installation, and component docs describe the Go daemon and manual board rollout steps.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace the release workflow's Cargo-based txing-unit-daemon build job with a Go build/test/package job that injects the release version into github.com/mparkachov/txing/devices/unit/daemon/internal/daemon.DaemonVersion and publishes txing-unit-daemon-linux-aarch64.tar.gz.
2. Keep the KVS release asset on txing-unit-kvs-master-linux-aarch64.tar.gz and update release/versioning assertions so release notes/checks cover the Go daemon job, new KVS asset name, and absence of active Cargo unit-daemon release paths.
3. Move release version management for the active daemon from devices/unit/daemon/Cargo.toml/Cargo.lock to devices/unit/daemon/internal/daemon/version.go while leaving non-active Rust source untouched.
4. Update current board, artifacts, installation, component, and agent guidance text from Rust daemon wording to Go daemon wording without changing protocols, env names, sockets, manual rollout, or old-unit cleanup notes.
5. Validate with release version check, shared versioning tests, Go daemon tests/build with injected version output, and searches for stale active Rust/Cargo release-doc references.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Switched the release workflow's txing-unit-daemon artifact from the Cargo daemon job to a Go build/test/package job with DaemonVersion ldflags injection, kept the public asset name txing-unit-daemon-linux-aarch64.tar.gz, and made publish depend on build-go-unit-daemon. Kept KVS release packaging on txing-unit-kvs-master-linux-aarch64.tar.gz. Moved active release version management from devices/unit/daemon/Cargo.toml/Cargo.lock to devices/unit/daemon/internal/daemon/version.go and updated KVS version checking to kTxingUnitKvsMasterVersion. Updated active board/artifacts/installation/component docs and board agent guidance to describe the Go daemon while preserving manual rollout and retired unit cleanup notes. Updated local daemon test/run and docker-build recipes to use Go for active daemon builds.

Validation passed: python3 release/src/txing_release/cli.py check; go test ./... from devices/unit/daemon with workspace-local Go caches; GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build with DaemonVersion=9.8.7-test produced a statically linked Linux arm64 txing-unit-daemon; native injected build printed txing-unit-daemon 9.8.7-test; just --justfile devices/unit/daemon/justfile test passed with workspace-local Go caches; python -m unittest shared.aws.python.tests.test_versioning passed; ruby YAML parse of .github/workflows/release.yml passed; tar audit listed only root-level txing-unit-daemon; rg checks found no active Rust/Cargo unit-daemon release references and old board names only in migration docs/tests.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Release and current docs now use the Go txing-unit-daemon as the active board daemon. The release workflow builds/tests/packages the Go daemon with version injection, publishes the same txing-unit-daemon-linux-aarch64.tar.gz asset, keeps txing-unit-kvs-master-linux-aarch64.tar.gz, and removes the active Cargo daemon release job. Versioning/docs tests now assert the Go daemon, txing-unit-kvs-master, and txing-unit.target surfaces.
<!-- SECTION:FINAL_SUMMARY:END -->
