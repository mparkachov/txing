# office subproject guide

## Scope
- This directory contains the React/Vite SPA for admin management of Thing Shadow.

## Notes
- Run frontend package manager, build, and test commands from `office/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Read `../docs/constraints/repository-rules.md` before changing office build,
  hosting, deployment, Cognito, or AWS configuration behavior.
- Read `../docs/contracts/unit-device-contracts.md` before changing unit
  shadow, capability, video, MCP, or active-control UI behavior.
- Use `../devices/unit/aws/*-shadow.schema.json` as the canonical shadow JSON structure for the current `unit` device type.
- Treat the office app as a consumer of shared shadow contracts rather than an owner of the `mcu.*` or `board.*` subtrees.
- Do not derive board/MCP/video availability locally from pending commands or
  client-side transport state; use the Sparkplug named shadow projection.
- Do not add a `/* /index.html 200` `_redirects` rule for Cloudflare Pages.
- Do not add `txing.dev` as a Cognito callback URL for the public sign-in
  entry flow; the public site links to `https://office.txing.dev/?signin=1`.
- Do not add `VITE_TXING_VERSION`, `VITE_DEVICE_THING_NAME`, or
  `VITE_SPARKPLUG_EDGE_NODE_ID` to office Cloudflare configuration.

## Shared workflow
- Follow the repository-level Backlog.md workflow in `../AGENTS.md`.
- If an office-specific task is created under a shared milestone, mention
  `office/` in the Backlog task title or description so ownership is obvious.
