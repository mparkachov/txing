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
