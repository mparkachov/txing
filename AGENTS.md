# txing agent guide

## Repository structure
- `mcu/`: Rust firmware subproject for the MCU.
- `gw/`: Python subproject for the Raspberry Pi 5 gateway (AWS IoT MQTT + BLE communication with MCU).
- `board/`: Python subproject for the device-side Raspberry Pi board control (AWS IoT MQTT shadow control/reporting).
- `web/`: React/Vite SPA for admin management of Thing Shadow.

## Working rules
- Treat this repository as a monorepo with the subprojects above.
- Keep changes scoped to the relevant subproject.
- Do not perform `git commit` automatically.
- Create commits only when explicitly requested by the user.
- Flashing/programming firmware onto hardware must only be performed manually by the user. Agents may prepare artifacts and commands, but must not run flashing steps automatically.

## Shared contracts
- Thing Shadow schema source of truth: `docs/txing-shadow.schema.json`.
- Shadow behavior contract: `docs/device-gateway-shadow-spec.md`.
- Ownership rule: `gw` owns the `mcu.*` shadow subtree contract.
- Ownership rule: `board` owns the `board.*` shadow subtree contract.

## Board Video Phase 1
- Phase 1 board video is a headless network-service design. Do not assume any GUI, local browser, or desktop session on the board.
- `txing-board` remains the only publisher of `board.*` Thing Shadow updates.
- Phase 1 local video uses a dedicated media service plus MediaMTX for board-local WebRTC/WHEP serving.
- Phase 1 browser authentication uses a read-only bearer token generated on the board, mirrored into `board.*` by `txing-board`, and consumed by `web`.
- Phase 1 keeps a future `kvssink` branch in mind but does not implement cloud upload yet.
- Browser-to-board control transport is out of scope for board video phase 1 and must not be treated as already decided.

## Terminology
- `power=true` means the device is in the wakeup state.
- `power=false` means the device is in the sleep state.
- In the sleep state, the MCU stays in RTC-driven low-power idle between periodic rendezvous wakeups.
- The sleep-state rendezvous interval is every `5 s`: the MCU wakes briefly, refreshes BLE state, advertises for a bounded window, and returns to low-power idle if no BLE session is needed.
- Use `wakeup state` / `sleep state` when describing the external device power contract. Distinguish that from the firmware's internal `Wake` step inside the sleep-state rendezvous cycle.
