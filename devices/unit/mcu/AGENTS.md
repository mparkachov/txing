# mcu subproject guide

## Scope
- This directory contains the Rust firmware for the MCU.

## Notes
- Run firmware build/test commands from `mcu/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../aws/shadow.schema.json` as the canonical shadow JSON structure.
- Treat `rig` as owner of the `mcu.*` shadow subtree contract.

## Shared workflow
- Follow the repository-level Beads workflow in `../AGENTS.md`.
- If an `mcu/`-specific task is created under a shared epic, mention `mcu/` in the Beads title or description so ownership is obvious.
