# web subproject guide

## Scope
- This directory contains the React/Vite SPA for admin management of Thing Shadow.

## Notes
- Run frontend package manager, build, and test commands from `web/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../docs/txing-shadow.schema.json` as the canonical shadow JSON structure.
- Treat the web app as a consumer of shared shadow contracts rather than an owner of the `mcu.*` or `board.*` subtrees.

## Package task scoping
When working in `web/`:
- If the work is not already under an open Beads epic, create the epic first, then create the web task under it.
- Prefer tasks already linked to the current epic.
- If a new subtask is web-specific, create it under the parent epic and note `web/` in the title or description.
- Do not duplicate cross-subproject work here; link dependencies in Beads instead.
- Do not use Codex task management or markdown TODOs as the authoritative tracker for web work; keep execution state in Beads.
