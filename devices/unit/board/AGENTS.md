# board subproject guide

## Scope
- This directory contains native board-side support code for the unit Raspberry Pi board video and local hardware adapter paths.
- This board is distinct from the `rig/` Raspberry Pi 5 gateway.
- The production board runtime is the Go `txing-unit-daemon`; this directory does not contain a Python board runtime.
- The native `txing-unit-kvs-master` worker connects to AWS KVS WebRTC signaling and communicates with `txing-unit-daemon` over the local BoardVideoBridge gRPC socket.
- The native `txing-unit-hardware-worker` owns board-local motor hardware access and communicates with `txing-unit-daemon` over the local UnitHardware gRPC socket.

## Notes
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Read `../../../docs/constraints/repository-rules.md` before changing board
  tooling, deployment, host runtime, AWS, or shell behavior.
- Read `../../../docs/contracts/unit-device-contracts.md` before changing board
  video, shadow ownership, retained MQTT topics, or runtime failure semantics.
- Read `../../../docs/contracts/unit-hardware-worker.md` before changing motor
  hardware ownership, worker gRPC API, or local failsafe behavior.
- Use `../aws/board-shadow.schema.json` as the canonical board shadow JSON structure when changing daemon-published board state.
- `txing-unit-daemon` owns and evolves the `board` named shadow contract for the `unit` device type.
- Hardware assumption: the board power rail is switched by an external low-side n-MOSFET driven from nRF pin `D0` / `P0.02`, so abrupt power loss is possible and `reportedAt` freshness matters more than best-effort shutdown updates.
- Stale board shadow or retained capability state after REDCON `4` must not be
  treated as current availability; fresh daemon state is required after wake.
- AWS-backed board services must wait for network-online and clock
  synchronization so TLS validation does not race NTP.

## Board Video
- Treat board video as a headless service-only design.
- `txing-unit-daemon` is the only process allowed to publish `board.*` updates into the Thing Shadow.
- The current implementation uses one live operator path only: board camera -> AWS KVS WebRTC signaling channel -> operator.
- The board does not expose a board-local viewer page, iframe endpoint, or direct browser-to-board media transport.
- `txing-unit-daemon` serves the BoardVideoBridge gRPC socket, publishes retained video descriptor/status topics for `rig`, and mirrors descriptor/status into the `video` named shadow for readers.
- `txing-unit-daemon` vends IoT credentials to the native worker for KVS access through the bridge.
- The current implementation does not use MediaMTX, `webrtcsink`, `gstwebrtc-api`, `kvssink`, ingestion/storage, or multiviewer.

## Hardware Worker
- `txing-unit-hardware-worker` must stay subordinate to `txing-unit-daemon`.
- The worker owns GPIO, PWM, I2C, CAN, vendor SDK, calibration, command application, local hardware readiness, and local motor neutralization.
- The worker must not own MCP sessions, active-control policy, REDCON policy, cloud publication, Thing Shadow state, or public authorization.

## Shared workflow
- Follow the repository-level workflow in `../../../AGENTS.md`.
