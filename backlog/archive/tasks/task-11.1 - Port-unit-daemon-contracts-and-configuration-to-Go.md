---
id: TASK-11.1
title: Port unit daemon contracts and configuration to Go
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 14:30'
updated_date: '2026-05-23 16:18'
labels: []
milestone: Go unit board daemon replacement
dependencies: []
references:
  - devices/unit/daemon
  - devices/unit/proto/txing/unit/board_video/v1/board_video.proto
  - devices/unit/proto/txing/unit/hardware/v1/unit_hardware.proto
  - devices/unit/daemon/daemon.env.template
documentation:
  - >-
    backlog/docs/architecture/unit-daemon-go-reimplementation/doc-1 -
    Unit-daemon-Go-reimplementation.md
  - >-
    backlog/docs/constraints/unit-board-daemon-go-parity/doc-3 -
    Constraints-unit-board-daemon-Go-parity.md
parent_task_id: TASK-11
modified_files:
  - devices/unit/daemon/.gitignore
  - devices/unit/daemon/go.mod
  - devices/unit/daemon/go.sum
  - devices/unit/daemon/cmd/txing-unit-daemon/main.go
  - devices/unit/daemon/internal/daemon/config.go
  - devices/unit/daemon/internal/daemon/config_test.go
  - devices/unit/daemon/internal/daemon/payloads.go
  - devices/unit/daemon/internal/daemon/topics.go
  - devices/unit/daemon/internal/daemon/topics_payloads_test.go
  - devices/unit/daemon/internal/daemon/version.go
  - devices/unit/daemon/internal/proto/boardvideov1/board_video.pb.go
  - devices/unit/daemon/internal/proto/boardvideov1/board_video_grpc.pb.go
  - devices/unit/daemon/internal/proto/hardwarev1/unit_hardware.pb.go
  - devices/unit/daemon/internal/proto/hardwarev1/unit_hardware_grpc.pb.go
ordinal: 12000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A Go module and txing-unit-daemon command exist under devices/unit/daemon and preserve the existing --version behavior with injected release version support.
- [x] #2 Go protobuf bindings are generated from the existing BoardVideoBridge and UnitHardware proto files without changing wire contracts.
- [x] #3 Config parsing preserves existing CLI flags, TXING_* env names, env-file loading, precedence, defaults, validation, and colocated certificate behavior.
- [x] #4 Ported Go tests cover the current configuration, topic-building, env parsing, version, and static payload behavior.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the current Rust daemon CLI/config/topic/version/static payload tests and proto generation inputs as the source of truth.
2. Add a Go module under `devices/unit/daemon` with `cmd/txing-unit-daemon`, generated protobuf bindings from the existing board video and hardware proto files, and release-version injection.
3. Port the daemon configuration model, env-file parser, CLI/env/default precedence, validation, topic helpers, certificate colocation behavior, and static payload helpers into Go without changing public names.
4. Add focused Go tests for version output, config/env parsing, topic construction, certificate resolution, and static payload behavior; run the relevant Go and existing Rust parity tests where available.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added a Go module in `devices/unit/daemon` with `cmd/txing-unit-daemon`, version output backed by `internal/daemon.DaemonVersion` for `-ldflags -X` release injection, generated Go gRPC/protobuf bindings for the existing BoardVideoBridge and UnitHardware proto files, and a focused Go port of the Rust daemon's configuration, env-file loading, topic helpers, board/capability/static descriptor payloads, validation, defaults, and colocated certificate resolution. The original proto files were not changed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-11.1 is complete. Verified the Go module with `go test ./...`, verified injected version output with `go build -ldflags '-X github.com/mparkachov/txing/devices/unit/daemon/internal/daemon.DaemonVersion=9.8.7-test'` and `txing-unit-daemon --version`, confirmed `devices/unit/proto` has no diff, and reran the existing Rust daemon unit suite with `cargo test --lib` using sandbox-local Cargo caches.
<!-- SECTION:FINAL_SUMMARY:END -->
