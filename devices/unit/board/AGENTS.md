# board subproject guide

## Scope
- This directory contains native board-side support code for the unit Raspberry Pi board video path.
- This board is distinct from the `rig/` Raspberry Pi 5 gateway.
- The production board runtime is the Rust `txing-unit-daemon`; this directory does not contain a Python board runtime.
- The native `txing-board-kvs-master` worker connects to AWS KVS WebRTC signaling and is supervised by `txing-unit-daemon`.

## Notes
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../aws/board-shadow.schema.json` as the canonical board shadow JSON structure when changing daemon-published board state.
- `txing-unit-daemon` owns and evolves the `board` named shadow contract for the `unit` device type.
- Hardware assumption: the board power rail is switched by an external low-side n-MOSFET driven from nRF pin `D0` / `P0.02`, so abrupt power loss is possible and `reportedAt` freshness matters more than best-effort shutdown updates.

## Board Video
- Treat board video as a headless service-only design.
- `txing-unit-daemon` is the only process allowed to publish `board.*` updates into the Thing Shadow.
- The current implementation uses one live operator path only: board camera -> AWS KVS WebRTC signaling channel -> operator.
- The board does not expose a board-local viewer page, iframe endpoint, or direct browser-to-board media transport.
- `txing-unit-daemon` supervises `txing-board-kvs-master`, publishes retained video descriptor/status topics for `rig`, and mirrors descriptor/status into the `video` named shadow for readers.
- `txing-unit-daemon` vends IoT credentials to the supervised native worker for KVS access.
- The current implementation does not use MediaMTX, `webrtcsink`, `gstwebrtc-api`, `kvssink`, ingestion/storage, or multiviewer.

## Shared workflow
- Follow the repository-level workflow in `../../../AGENTS.md`.
