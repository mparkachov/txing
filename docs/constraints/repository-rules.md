# Repository rules and operational constraints

These constraints apply across the repository. Read this document before
changing tooling, deployment, host runtime behavior, infrastructure, release
logic, shell scripts, or firmware programming workflows.

## General scope

- Treat this repository as a monorepo.
- Keep changes scoped to the relevant subproject unless a shared contract or
  consistency issue requires a coordinated update.
- Prefer moving development to new functionality without preserving backward
  compatibility, except for protocols and protocol versions. Before making a
  change that drops or ignores backward compatibility, ask the user every time
  whether that is acceptable.

## Repository boundaries

- Do not read from, copy from, execute from, or depend on files outside
  `/Users/Maxim/Developer/txing` unless the user explicitly provides the content
  in the conversation or explicitly asks to vendor it into the repository first.
- Do not create commits unless explicitly requested by the user.

## Shell and Justfiles

- `just` recipe arguments in this repository are positional. Do not invoke
  recipes with `name=value` syntax such as
  `just unit::daemon::cert thing_id=unit-bl95f2`; pass values positionally, for
  example `just unit::daemon::cert unit-bl95f2`.
- Repository shell code must be strictly POSIX `sh` compatible. Use
  `#!/bin/sh`, `set -eu`, and `.` for sourcing.
- Do not use Bash/Zsh-only features such as arrays, `[[ ... ]]`, `=~`,
  `mapfile`/`readarray`, process substitution, here strings, `local`,
  `printf %q`, or `pipefail`.
- Just recipes must use POSIX shell syntax so they run under macOS Bash 3.2,
  zsh, and other POSIX shells.
- Justfiles must export `TMPDIR` to the repository-local `./tmp` directory by
  default.
- Host temp directories such as `/tmp` or macOS `/var/folders/...` must not be
  the default scratch location for repository scripts. Create `./tmp` before
  using it from standalone scripts.

## AWS and infrastructure safety

- Do not run commands against AWS that could create, update, or delete cloud
  resources.
- Read-only AWS inspection commands are allowed only when needed.
- Never add CloudFormation, custom-resource, migration, rollback, or cleanup
  logic that deletes or mutates manually rolled-in resources.
- Resources created manually by an operator must remain untouched across
  CloudFormation deploy, update, rollback, and delete unless the user explicitly
  asks for that exact destructive operation.
- Prefer manual cleanup plus CloudFormation-forward changes over
  backward-compatible migration code.
- When existing AWS resources must be removed, renamed, imported, or otherwise
  reconciled, explain the required manual steps and let the user perform them.

## Host runtime and privilege assumptions

- Do not write host-side runtime code, installer scripts, release assets, or
  generated commands that assume they run as root.
- Do not use `sudo` inside repository code intended to run on deployed hosts.
- When privileged host configuration is required, provide explicit manual steps
  for the user to run in chat or docs.

## Release, deployment, and firmware

- After every code, firmware, infrastructure, or configuration change, explain
  the relevant deployment or rollout steps in the final response, including any
  manual steps the user must perform.
- When a new immutable release or host/runtime artifact version is required,
  inform the user to bump the whole project to a new release version.
- Do not add deploy bypasses or automated component version enforcement
  checks.
- Preserve the current release separation: the release workflow publishes
  artifacts, but does not bump versions, commit, push back to a branch, upload
  Lambda code to AWS, or deploy to hosts.
- Do not turn manual board, rig, AWS, or release operator steps into automatic
  scripts unless the user explicitly asks for that exact automation.
- Flashing/programming firmware onto hardware must only be performed manually by
  the user. Agents may prepare artifacts and commands, but must not run flashing
  steps automatically.

## Naming and generated material

- IAM roles, IAM managed policies, IoT role aliases, and IoT policies use
  CloudFormation-generated physical names. Do not depend on old fixed names;
  use `/txing/stack/...` parameters or AWS API lookups.
- Do not commit generated certificate material or daemon config tarballs from
  `certs/`.
