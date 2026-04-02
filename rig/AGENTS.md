# rig subproject guide

## Scope
- This directory contains the Python rig runtime for Raspberry Pi 5.
- Rig responsibilities include direct AWS IoT MQTT integration and BLE communication with the MCU.

## Notes
- Run Python and `uv` commands from `rig/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../docs/txing-shadow.schema.json` as the canonical shadow JSON structure.
- `rig` owns and evolves the `mcu.*` shadow subtree contract.

## Package task scoping
When working in `rig/`:
- If the work is not already under an open Beads epic, create the epic first, then create the rig task under it.
- Prefer tasks already linked to the current epic.
- If a new subtask is rig-specific, create it under the parent epic and note `rig/` in the title or description.
- Do not duplicate cross-subproject work here; link dependencies in Beads instead.
- Do not use Codex task management or markdown TODOs as the authoritative tracker for rig work; keep execution state in Beads.
