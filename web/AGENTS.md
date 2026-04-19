# web subproject guide

## Scope
- This directory contains the React/Vite SPA for admin management of Thing Shadow.

## Notes
- Run frontend package manager, build, and test commands from `web/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../devices/unit/aws/shadow.schema.json` as the canonical shadow JSON structure for the current `unit` device type.
- Treat the web app as a consumer of shared shadow contracts rather than an owner of the `mcu.*` or `board.*` subtrees.

## Shared workflow
- Follow the repository-level Beads workflow in `../AGENTS.md`.
- If a web-specific task is created under a shared epic, mention `web/` in the Beads title or description so ownership is obvious.
