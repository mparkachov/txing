# board subproject guide

## Scope
- This directory contains the single native board-side implementation shared by
  every board device type: the Go daemon, the KVS master, and the hardware
  worker. There is no per-device copy of any of them.
- The device type is a build input, not a source axis. `TXING_BOARD_DEVICE_TYPE`
  selects the proto package, binary names, socket paths, and the release stream
  the version is injected from. Nothing in this tree may branch on the device
  type any other way.
- Genuinely per-device material stays under `devices/<device>/`: the
  `manifest.toml` profile, shadow schemas and defaults in `aws/`, the web
  adapter, and the proto package.
- This board is distinct from the `rig/` Raspberry Pi 5 gateway.
- The production board runtime is the Go `txing-<device>-daemon`; this directory
  does not contain a Python board runtime.
- `txing-<device>-kvs-master` connects to AWS KVS WebRTC signaling and talks to
  the daemon over the local BoardVideoBridge gRPC socket.
- `txing-<device>-hardware-worker` owns board-local motor hardware access and
  talks to the daemon over the local BoardHardware gRPC socket.

## Notes
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Read `../../../docs/constraints/repository-rules.md` before changing board
  tooling, deployment, host runtime, AWS, or shell behavior.
- Read `../../../docs/contracts/unit-device-contracts.md` before changing board
  video, shadow ownership, retained MQTT topics, or runtime failure semantics.
  It carries the device-agnostic board behavior contract that every device type
  follows.
- Read `../../../docs/contracts/unit-hardware-worker.md` before changing motor
  hardware ownership, worker gRPC API, or local failsafe behavior.
- Use `../../<device>/aws/board-shadow.schema.json` as the canonical board shadow
  JSON structure when changing daemon-published board state.
- The daemon owns and evolves the `board` named shadow contract for its device type.
- Hardware assumption: the board power rail is switched by an external low-side n-MOSFET driven from nRF pin `D0` / `P0.02`, so abrupt power loss is possible and `reportedAt` freshness matters more than best-effort shutdown updates.
- Stale board shadow or retained capability state after REDCON `4` must not be
  treated as current availability; fresh daemon state is required after wake.
- AWS-backed board services must wait for network and clock synchronization so
  TLS validation does not race NTP.
- The signaling trust anchor must stay runtime-selectable through
  `TXING_KVS_SYSTEM_CA_CERT_PATH`. The KVS SDK's TLS layer verifies against a
  single anchor and fails against a full OS CA bundle.

## Board Video
- Treat board video as a headless service-only design.
- The daemon is the only process allowed to publish `board.*` updates into the Thing Shadow.
- The current implementation uses one live operator path only: board camera -> AWS KVS WebRTC signaling channel -> operator.
- The board does not expose a board-local viewer page, iframe endpoint, or direct browser-to-board media transport.
- The daemon serves the BoardVideoBridge gRPC socket, publishes retained video descriptor/status topics for `rig`, and mirrors descriptor/status into the `video` named shadow for readers.
- The daemon vends IoT credentials to the native worker for KVS access through the bridge.
- The current implementation does not use MediaMTX, `webrtcsink`, `gstwebrtc-api`, `kvssink`, ingestion/storage, or multiviewer.

## Hardware Worker
- The hardware worker must stay subordinate to the daemon.
- The worker owns GPIO, PWM, I2C, CAN, vendor SDK, calibration, command application, local hardware readiness, and local motor neutralization.
- The worker must not own MCP sessions, active-control policy, REDCON policy, cloud publication, Thing Shadow state, or public authorization.

## Shared workflow
- Follow the repository-level workflow in `../../../AGENTS.md`.
