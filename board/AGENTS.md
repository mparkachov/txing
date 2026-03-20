# board subproject guide

## Scope
- This directory contains the Python software for the device-side Raspberry Pi board.
- This board is distinct from the `gw/` Raspberry Pi 5 gateway.
- The board process connects directly to AWS IoT over MQTT/mTLS and publishes `state.reported.board` in the shared Thing Shadow.

## Notes
- Run Python and `uv` commands from `board/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../docs/txing-shadow.schema.json` as the canonical shadow JSON structure.
- `board` owns and evolves the `board.*` shadow subtree contract.
- Use the shared AWS IoT mTLS client artifacts in `../certs/txing.cert.pem` and `../certs/txing.private.key`, matching `gw/`.
- Hardware assumption: the board power rail is switched by an external low-side n-MOSFET driven from nRF pin `D0` / `P0.02`, so abrupt power loss is possible and `reportedAt` freshness matters more than best-effort shutdown updates.

## Board Video Phase 1
- Treat board video phase 1 as a headless service-only design.
- `txing-board` is the only process allowed to publish `board.*` updates into the Thing Shadow.
- Phase 1 local video is served through a dedicated media service and MediaMTX, not through a GUI example or local browser.
- Phase 1 web authentication for local video uses a read-only token generated on the board and surfaced to the web app through the `board.*` shadow subtree by `txing-board`.
- Keep the design compatible with a later `kvssink` branch, but do not implement cloud upload in phase 1.
- Browser-to-board control transport is deferred beyond phase 1 unless the user explicitly changes that decision.
