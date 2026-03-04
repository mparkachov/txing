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

## Task Runner

This monorepo standardizes on `just` as the task runner.

Run from repository root:

```bash
just --list
just gw::wake
just aws::bootstrap
just mcu::build
```

Subproject `justfile`s are included by the root `justfile` as modules:
- `gw::...` -> `gw/justfile`
- `aws::...` -> `aws/justfile`
- `mcu::...` -> `mcu/justfile`

Firmware example:

```bash
just mcu::build
```

Gateway example:

```bash
cd gw
uv run gw
```
