# board subproject guide

## Scope
- This directory contains the Python software for the device-side Raspberry Pi board.
- This board is distinct from the `rig/` Raspberry Pi 5 gateway.
- The board process connects directly to AWS IoT over SigV4-authenticated MQTT over WebSockets and publishes `state.reported.board` in the shared Thing Shadow.

## Notes
- Run Python and `uv` commands from `board/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../aws/shadow.schema.json` as the canonical shadow JSON structure.
- `board` owns and evolves the `board.*` shadow subtree contract.
- Use the shared project-local AWS config flow with profiles `town`, `rig`, and `txing`; `board/` stays an internal package name, not the public AWS runtime identity.
- Hardware assumption: the board power rail is switched by an external low-side n-MOSFET driven from nRF pin `D0` / `P0.02`, so abrupt power loss is possible and `reportedAt` freshness matters more than best-effort shutdown updates.

## Board Video
- Treat board video as a headless service-only design.
- `txing-board` is the only process allowed to publish `board.*` updates into the Thing Shadow.
- The current implementation uses one live operator path only: board camera -> AWS KVS WebRTC signaling channel -> operator.
- The board does not expose a board-local viewer page, iframe endpoint, or direct browser-to-board media transport.
- `txing-board` supervises a dedicated local video sender and publishes retained video descriptor/status topics for `rig`; `rig` reflects top-level `reported.video.*` into the Thing Shadow.
- The supervised sender uses the board host's default AWS SDK credential chain for KVS access, and `board.video_service` publishes the retained AWS IoT video topics.
- The current implementation does not use MediaMTX, `webrtcsink`, `gstwebrtc-api`, `kvssink`, ingestion/storage, or multiviewer.

## Shared workflow
- Follow the repository-level Beads workflow in `../AGENTS.md`.
- If a board-specific task is created under a shared epic, mention `board/` in the Beads title or description so ownership is obvious.
