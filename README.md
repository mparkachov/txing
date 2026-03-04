# txing

Monorepo root for `txing`.

- MCU firmware lives in `mcu/` (Rust).
- Gateway software lives in `gw/` (Python, direct AWS IoT MQTT + BLE bridge).
- Shared docs live in `docs/`.
- Thing Shadow contract schema lives in `docs/txing-shadow.schema.json`.
- Thing Shadow guidance lives in `docs/thing-shadow.md`.
- High-level path: `AWS IoT Device Shadow -> MQTT -> gw -> BLE -> mcu`.

## System requirements

For gateway workflows in this repository, install and configure:
- `uv`
- `just`
- `jq`
- `aws` (AWS CLI)

AWS CLI must be configured with credentials/profile and region.

Run commands from the relevant subproject.

Firmware example:

```bash
cd mcu
cargo mcu build
```

Gateway example:

```bash
cd gw
uv run gw
```
