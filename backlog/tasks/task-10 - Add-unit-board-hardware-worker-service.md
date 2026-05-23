---
id: TASK-10
title: Add unit board hardware worker service
status: Done
assignee:
  - '@codex'
created_date: '2026-05-23 12:23'
updated_date: '2026-05-23 14:46'
labels: []
dependencies: []
references:
  - devices/unit/daemon/src/lib.rs
  - devices/unit/board/kvs_master/CMakeLists.txt
documentation:
  - docs/contracts/unit-device-contracts.md
  - docs/components/board.md
  - docs/contracts/board-video-bridge.md
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Introduce txing-unit-hardware-worker as the board-local C++ hardware adapter for motor cmd_vel execution while txing-unit-daemon keeps MCP, active-control, REDCON, and publication authority.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A C++ txing-unit-hardware-worker exposes a local versioned gRPC UnitHardware API with GetStatus, ApplyVelocity, and Stop over a Unix domain socket.
- [x] #2 The worker preserves current strict cmd_vel Twist validation, differential tank mixing, PWM/GPIO motor output, and local failsafe neutralization on expiry, shutdown, disconnect, and hardware errors.
- [x] #3 txing-unit-daemon validates MCP active control first, delegates accepted cmd_vel commands to the worker, maps worker motion into existing MCP responses, and rejects actuator commands while the worker is unavailable.
- [x] #4 Board install, systemd target, release/build plumbing, and tests cover the new worker without giving it MCP, REDCON, cloud, or publication authority.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add the UnitHardware v1 proto and generate Rust/C++ bindings through the existing daemon build and CMake patterns.\n2. Add the C++ txing-unit-hardware-worker with config parsing, strict Twist validation, differential mixing, fake-testable PWM/GPIO driver boundaries, Unix-socket gRPC server, and local failsafe stop handling.\n3. Replace the daemon's in-process motor driver with a bounded gRPC client that preserves MCP active-control checks and response shape while treating worker unavailability as actuator unavailable.\n4. Update board install/release/build docs and workflow plumbing for the new binary and systemd service.\n5. Run focused Rust and C++ tests plus available release metadata tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented UnitHardware v1 proto, C++ worker core/server, Rust daemon gRPC client delegation, board systemd/release docs, release workflow artifact plumbing, and release/version policy coverage. Validation passed: daemon cargo tests, hardware worker core CMake/CTest tests, shared AWS release/install policy tests, and release version-surface check. Local gRPC-enabled C++ configure was not run to completion on macOS because Protobuf/gRPC development packages are not installed in this host environment; the Linux aarch64 release job installs those packages.
<!-- SECTION:NOTES:END -->
