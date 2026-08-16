# Repository editing and operational boundaries

This file holds agent-facing edit boundaries that are easy to miss when they
live inside user-facing component, install, or operations documentation. Read it
before broad refactors, dependency cleanup, release/deploy work, web hosting,
tooling, shell, infrastructure, or future-work implementation.

## Keep product docs and agent rules separate

- Keep product contracts in component docs when they describe runtime behavior
  that humans also need to understand.
- Put agent-only editing rules in root or nested `AGENTS.md` files, or in
  `docs/agent-guidance/` when the rule spans multiple subprojects.
- If a component doc says a behavior is current scope or explicitly out of
  scope, do not implement the out-of-scope behavior unless the user selects it
  as a goal or approves a new milestone.

## Repository and build rules

- Treat the repository as a monorepo and keep changes in the relevant
  subproject unless a shared contract or consistency issue requires a
  coordinated change.
- Do not read from, copy from, execute from, or depend on files outside this
  repository unless the user provides their content or explicitly asks to vendor
  them into the repository.
- `just` recipe arguments are positional. For example, use
  `just unit::board::role-policy unit-bl95f2`, not
  `just unit::board::role-policy thing_id=unit-bl95f2`.
- Repository shell code and Just recipes must be POSIX `sh`: use `#!/bin/sh`,
  `set -eu`, and `.` for sourcing. Do not use Bash/Zsh-only syntax.
- Justfiles export `TMPDIR` to the repository-local `./tmp` directory. Other
  repository scripts create and use `./tmp`; do not use host temporary
  directories as their default scratch location.

## AWS, host, and generated-material safety

- Do not run AWS commands that create, update, or delete resources. Read-only
  inspection is allowed only when needed.
- Do not add CloudFormation, custom-resource, migration, rollback, or cleanup
  logic that mutates manually rolled-in resources. Explain required manual
  cleanup and use CloudFormation-forward changes instead.
- Do not write deployed host code, installer scripts, release assets, or
  generated commands that assume `root`, and do not put `sudo` in deployed
  repository code. Describe privileged work as explicit manual operator steps.
- Narrow exception, board initial installation only: the board's first-boot
  card may configure base Alpine OS setup (Wi-Fi, `wlan0`, root SSH access, apk
  repositories, package upgrade, the fixed board runtime-package baseline, and
  the mise bootstrap). Device release artifacts, daemon configuration, service
  installation, and every update on a board already in service remain manual
  operator actions. Card files carry no AWS credentials, daemon configuration,
  or release material.
- IAM roles, managed policies, IoT role aliases, and IoT policies use
  CloudFormation-generated physical names. Use `/txing/stack/...` parameters or
  AWS API lookups; do not depend on historical fixed names.
- Never commit generated certificates or daemon configuration tarballs from
  `certs/`.

## Release and deployment boundaries

- Do not turn manual operator install, release, AWS, board, or rig maintenance
  docs into automatic scripts unless the user explicitly asks for that exact
  automation.
- Release artifacts are immutable for each exact component version; do not add
  deploy bypasses around release versioning.
- When a change requires a new release artifact, tell the user which component
  version must be bumped before publishing it.
- The release workflow does not bump versions, commit, push, publish Lambda
  code to AWS, or publish host binaries. Preserve that separation.
- Production board and rig binary updates remain manual writable-root
  maintenance actions through root-owned `mise`.
- Do not add deploy bypasses or automated component-version enforcement checks.
- Flashing or programming firmware is a manual operator action; agents may only
  prepare artifacts and commands.

## AWS and Cloudflare editing boundaries

- Do not add repo-local operational state for AWS bring-up, hidden certificate
  paths, or generated AWS config.
- IAM roles, IAM managed policies, IoT role aliases, and IoT policies use
  CloudFormation-generated physical names. Do not depend on old fixed names;
  use `/txing/stack/...` parameters or AWS API lookups.
- Cloudflare Pages publishing for `office/` and `www/` is Git-driven. Do not
  add `npx wrangler deploy` or a custom deploy command.
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
