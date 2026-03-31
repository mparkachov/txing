# rig subproject guide

## Scope
- This directory contains the Python rig runtime for Raspberry Pi 5.
- Rig responsibilities include direct AWS IoT MQTT integration and BLE communication with the MCU.

## Notes
- Run Python and `uv` commands from `rig/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../docs/txing-shadow.schema.json` as the canonical shadow JSON structure.
- `rig` owns and evolves the `mcu.*` shadow subtree contract.
