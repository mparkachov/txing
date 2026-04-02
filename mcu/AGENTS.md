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
- If the work comes from `/plan` and is already under a Beads epic, prefer tasks already linked to that current epic.
- If the work is not `/plan`-driven, a standalone Beads issue is sufficient; do not create a new epic just for routine firmware work.
- If a new firmware-specific subtask belongs to a plan-created epic, create it under the parent epic and note `mcu/` in the title or description.
- Do not duplicate cross-subproject work here; link dependencies in Beads instead.
- Do not use Codex task management or markdown TODOs as the authoritative tracker for firmware work; keep execution state in Beads.
