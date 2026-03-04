# txing agent guide

## Repository structure
- `mcu/`: Rust firmware subproject for the MCU.
- `gw/`: Python subproject for the Raspberry Pi 5 gateway (AWS IoT MQTT + BLE communication with MCU).

## Working rules
- Treat this repository as a monorepo with the two subprojects above.
- Keep changes scoped to the relevant subproject.
- Do not perform `git commit` automatically.
- Create commits only when explicitly requested by the user.

## Shared contracts
- Thing Shadow schema source of truth: `docs/txing-shadow.schema.json`.
- Shadow behavior contract: `docs/device-gateway-shadow-spec.md`.
- Ownership rule: `gw` owns the `mcu.*` shadow subtree contract.
