# board subproject guide

## Scope
- This directory contains the Python software for the device-side Raspberry Pi board.
- This board is distinct from the `rig/` Raspberry Pi 5 gateway.
- The board process connects directly to AWS IoT over MQTT/mTLS and publishes `state.reported.board` in the shared Thing Shadow.

## Notes
- Run Python and `uv` commands from `board/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../docs/txing-shadow.schema.json` as the canonical shadow JSON structure.
- `board` owns and evolves the `board.*` shadow subtree contract.
- Use the shared AWS IoT mTLS client artifacts in `../certs/txing.cert.pem` and `../certs/txing.private.key`, matching `rig/`.
- Hardware assumption: the board power rail is switched by an external low-side n-MOSFET driven from nRF pin `D0` / `P0.02`, so abrupt power loss is possible and `reportedAt` freshness matters more than best-effort shutdown updates.

## Board Video Phase 1
- Treat board video phase 1 as a headless service-only design.
- `txing-board` is the only process allowed to publish `board.*` updates into the Thing Shadow.
- Phase 1 uses one live operator path only: board camera -> AWS KVS WebRTC signaling channel -> operator.
- The board does not expose a board-local viewer page, iframe endpoint, or direct browser-to-board media transport.
- `txing-board` supervises a dedicated local video sender and publishes coarse `board.video.*` readiness, session metadata, viewer presence, and failures into the Thing Shadow.
- The supervised sender uses the board host's default AWS SDK credential chain for KVS access; it does not publish to AWS IoT directly.
- Phase 1 does not use MediaMTX, `webrtcsink`, `gstwebrtc-api`, `kvssink`, ingestion/storage, or multiviewer.

## Package task scoping
When working in `board/`:
- Prefer tasks already linked to the current epic.
- If a new subtask is board-specific, create it under the parent epic and note `board/` in the title or description.
- Do not duplicate cross-subproject work here; link dependencies in Beads instead.
