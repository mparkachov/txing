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
- If the work is not already under an open Beads epic, create the epic first, then create the firmware task under it.
- Prefer tasks already linked to the current epic.
- If a new subtask is firmware-specific, create it under the parent epic and note `mcu/` in the title or description.
- Do not duplicate cross-subproject work here; link dependencies in Beads instead.
- Do not use Codex task management or markdown TODOs as the authoritative tracker for firmware work; keep execution state in Beads.
