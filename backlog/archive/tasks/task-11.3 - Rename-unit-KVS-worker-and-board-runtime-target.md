---
id: TASK-11.3
title: Rename unit KVS worker and board runtime target
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 14:30'
updated_date: '2026-05-23 15:42'
labels: []
milestone: Go unit board daemon replacement
dependencies: []
references:
  - devices/unit/board/kvs_master
  - docs/components/board.md
  - docs/artifacts.md
documentation:
  - >-
    backlog/docs/milestones/go-unit-board-daemon-replacement/doc-2 -
    Milestone-Go-unit-board-daemon-replacement.md
  - >-
    backlog/docs/constraints/unit-board-daemon-go-parity/doc-3 -
    Constraints-unit-board-daemon-Go-parity.md
modified_files:
  - .github/workflows/release.yml
  - devices/unit/board/AGENTS.md
  - devices/unit/board/kvs_master/CMakeLists.txt
  - devices/unit/board/kvs_master/include/kvs_master/aws_env.hpp
  - devices/unit/board/kvs_master/include/kvs_master/board_video_bridge.hpp
  - devices/unit/board/kvs_master/include/kvs_master/config.hpp
  - devices/unit/board/kvs_master/include/kvs_master/kvs_session.hpp
  - devices/unit/board/kvs_master/include/kvs_master/markers.hpp
  - devices/unit/board/kvs_master/include/kvs_master/runtime.hpp
  - devices/unit/board/kvs_master/include/kvs_master/version.hpp
  - devices/unit/board/kvs_master/include/kvs_master/video_capturer.hpp
  - devices/unit/board/kvs_master/src/board_video_bridge_stub.cpp
  - devices/unit/board/kvs_master/src/config.cpp
  - devices/unit/board/kvs_master/src/main.cpp
  - devices/unit/board/kvs_master/src/runtime.cpp
  - devices/unit/board/kvs_master/tests/test_main.cpp
  - devices/unit/daemon/internal/daemon/config.go
  - devices/unit/daemon/internal/daemon/runtime.go
  - devices/unit/daemon/internal/daemon/runtime_test.go
  - devices/unit/daemon/justfile
  - devices/unit/daemon/src/lib.rs
  - devices/unit/docs/board-video.md
  - docs/artifacts.md
  - docs/components/board.md
  - docs/contracts/board-video-bridge.md
  - docs/contracts/unit-hardware-worker.md
  - docs/installation.md
  - shared/aws/python/tests/test_versioning.py
parent_task_id: TASK-11
ordinal: 14000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The active native KVS worker executable, CMake target, test target, release asset, service name, mise alias, and docs use txing-unit-kvs-master.
- [x] #2 The daemon-served KVS worker client id and worker default client identity use txing-unit-kvs-master while the KVS signaling channel remains <thing-id>-board-video.
- [x] #3 Active board systemd docs and tests use txing-unit.target with txing-unit-daemon.service, txing-unit-kvs-master.service, and txing-unit-hardware-worker.service.
- [x] #4 Upgrade notes describe manual cleanup of old txing-board.target and txing-board-kvs-master.service on deployed boards.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Rename active native KVS worker surfaces from txing-board-kvs-master to txing-unit-kvs-master: CMake executable/test/install targets, worker CLI/version/default client identity text, daemon defaults/client IDs in Go and remaining Rust parity source, just recipes, and release workflow asset/binary variables.
2. Preserve protocol and channel compatibility: keep the KVS signaling channel pattern <thing-id>-board-video, keep TXING_BOARD_VIDEO_* environment names, and leave BoardVideoBridge proto/package/wire contracts unchanged.
3. Rename active board runtime target references from txing-board.target to txing-unit.target in installation/runtime docs and release/versioning tests, grouping txing-unit-daemon.service, txing-unit-kvs-master.service, and txing-unit-hardware-worker.service.
4. Add explicit upgrade notes for existing boards to disable/remove old txing-board.target and txing-board-kvs-master.service manually during the root-writable maintenance window; do not automate deployment or board cleanup.
5. Run the native KVS CTest target if available with local build dirs, run affected shared release/versioning tests, run Go daemon tests for renamed worker identity, and search to confirm old KVS/service/target names remain only in historical/migration notes or internal source-path identifiers where accepted.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Renamed active KVS master binary/build/test/release/docs surfaces to txing-unit-kvs-master and active board systemd target surfaces to txing-unit.target. Preserved BoardVideoBridge protocol names, TXING_BOARD_VIDEO_* environment names, and the <thing-id>-board-video signaling channel. Added manual cleanup notes for old txing-board.target and txing-board-kvs-master.service.

Validation passed: just --justfile devices/unit/daemon/justfile kvs-test-native; GOPATH=/Users/Maxim/Developer/txing/tmp/go/gopath GOMODCACHE=/Users/Maxim/Developer/txing/tmp/go/gopath/pkg/mod GOCACHE=/Users/Maxim/Developer/txing/tmp/go/build go test ./... from devices/unit/daemon; CARGO_HOME=/Users/Maxim/Developer/txing/tmp/cargo-home CARGO_TARGET_DIR=/Users/Maxim/Developer/txing/tmp/cargo-target cargo test --lib from devices/unit/daemon; python -m unittest shared.aws.python.tests.test_versioning; rg old-name check showing old names only in cleanup docs/tests.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Renamed unit board KVS worker and active board target surfaces to txing-unit-kvs-master and txing-unit.target, including daemon-served worker identity defaults, CMake/release targets, docs, and versioning assertions. Added deployed-board upgrade cleanup notes for the retired txing-board.target and txing-board-kvs-master.service.
<!-- SECTION:FINAL_SUMMARY:END -->
