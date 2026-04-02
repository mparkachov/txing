# mcu subproject guide

## Scope
- This directory contains the Rust firmware for the MCU.

## Notes
- Run firmware build/test commands from `mcu/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../docs/txing-shadow.schema.json` as the canonical shadow JSON structure.
- Treat `rig` as owner of the `mcu.*` shadow subtree contract.

## Package task scoping
When working in `mcu/`:
- Prefer tasks already linked to the current epic.
- If a new subtask is firmware-specific, create it under the parent epic and note `mcu/` in the title or description.
- Do not duplicate cross-subproject work here; link dependencies in Beads instead.
