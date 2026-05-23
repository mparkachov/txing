# Editing boundaries extracted from project docs

This file holds agent-facing edit boundaries that are easy to miss when they
live inside user-facing component, install, or operations documentation. Read it
before broad refactors, dependency cleanup, release/deploy work, web hosting
changes, or future-work implementation.

## Keep product docs and agent rules separate

- Keep product contracts in component docs when they describe runtime behavior
  that humans also need to understand.
- Put agent-only editing rules in root or nested `AGENTS.md` files, or in
  `docs/agent-guidance/` when the rule spans multiple subprojects.
- If a component doc says a behavior is current scope or explicitly out of
  scope, do not implement the out-of-scope behavior unless the user selects it
  as a goal or approves a new milestone.

## Release and deployment boundaries

- Do not turn manual operator install, release, AWS, board, or rig maintenance
  docs into automatic scripts unless the user explicitly asks for that exact
  automation.
- Release artifacts are immutable for each exact `VERSION`; do not add deploy
  bypasses around release versioning.
- The release workflow does not bump versions, commit, push, upload Lambda code
  to AWS, or deploy to hosts. Preserve that separation.
- Production board and rig binary updates remain manual writable-root
  maintenance actions through root-owned `mise`.

## AWS and Cloudflare editing boundaries

- Do not add repo-local operational state for AWS bring-up, hidden certificate
  paths, or generated AWS config.
- IAM roles, IAM managed policies, IoT role aliases, and IoT policies use
  CloudFormation-generated physical names. Do not depend on old fixed names;
  use `/txing/stack/...` parameters or AWS API lookups.
- Cloudflare Pages deployment for `office/` and `www/` is Git deployment. Do
  not add `npx wrangler deploy` or a custom deploy command.
- Do not add `VITE_TXING_VERSION`, `VITE_DEVICE_THING_NAME`, or
  `VITE_SPARKPLUG_EDGE_NODE_ID` to office Cloudflare configuration.
- Do not add a `/* /index.html 200` `_redirects` rule for the office SPA; Pages
  fallback is handled without that rule.

## Future-work boundaries

Cloud and control-only RTC consumers:

- Do not add a second KVS channel to the current `unit` path without an
  approved milestone.
- Do not add a cloud session consumer until there is a concrete product use
  case.
- Do not change the active-control protocol for this future work. Reuse
  `control.activate`, `takeover`, session identity, transport, and epoch
  enforcement unless a real protocol gap is found and the user approves it.
