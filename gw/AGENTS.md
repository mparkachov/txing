# gw subproject guide

## Scope
- This directory contains the Python gateway software for Raspberry Pi 5.
- Gateway responsibilities include direct AWS IoT MQTT integration and BLE communication with the MCU.

## Notes
- Run Python and `uv` commands from `gw/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../docs/txing-shadow.schema.json` as the canonical shadow JSON structure.
- `gw` owns and evolves the `mcu.*` shadow subtree contract.
