# Development

For the system overview, see [../README.md](../README.md). For the documentation map, see [README.md](./README.md).

## Repository Layout

- `devices/unit/`: self-contained current `unit` device type, including MCU, board runtime, rig process implementation, AWS shadow contracts, docs, and web detail adapter
- `rig/`: standalone Go daemons and host tooling for `raspi` rigs
- `devices/cloud-mcu/`: AWS-hosted `cloud` rig and `cloud-mcu` Lambda runtime
- `office/`: React + Vite admin/operator SPA
- `www/`: public static HTML/CSS/assets site for `txing.dev`
- `witness/`: Sparkplug-to-shadow projection Lambda source and tests
- `shared/aws/`: shared AWS CLI helpers, CloudFormation, and registry utilities
- `devices/template/`: scaffold for a new device type using the language-neutral manifest/process/web contracts

## Base Tooling

Repo-wide tooling:

- `uv`
- `just`
- `jq`
- AWS CLI v2
- GitHub CLI (`gh`) only for legacy release inspection or helper scripts

Host-specific setup starts in [installation.md](./installation.md). Detailed
board runtime setup, including read-only rootfs, lives in
[components/board.md](./components/board.md).

## Version And Artifact Channels

`VERSION` is the release version for the repository. It must stay a base
semantic version such as `x.y.z`.

Production release artifacts use `VERSION` exactly. Git SHA and dirty state are
exported separately for diagnostics. Create releases with the manual
`Txing Release` GitHub Actions workflow from the selected branch after bumping
and pushing the managed version files yourself. The workflow reads that branch's
root `VERSION`, fails unless it is newer than the latest existing `v*` tag,
publishes the GitHub Release, and also publishes the board, rig, and Lambda
artifacts. It does not commit or push version changes back to the selected
branch.

After a release workflow finishes, the operator Mac applies AWS infrastructure
changes and then asks the AWS-hosted publisher Lambda to publish Lambda
artifacts with:

```bash
just aws::deploy
just aws::publish latest
```

Development direction for installable host tools and board-side native
artifacts:

- release artifacts point at the artifact built from `VERSION`, for example `x.y.z`.
- GitHub release assets should be immutable for each exact artifact version.
- Board and rig host binaries use mise's GitHub backend directly; Lambda code
  is uploaded to AWS Lambda from GitHub release assets; see
  [artifacts.md](./artifacts.md).
- Board and rig binary updates are manual writable-root maintenance actions. The
  installed systemd service starts offline from root-owned mise shims and does
  not call GitHub during normal service restart.

## Operator AWS Config

Native AWS CLI configuration is the source of truth for AWS account,
credentials, selected profile, and region. `TXING_AWS_STACK` and optional
selected thing IDs come from the operator shell. `TXING_AWS_STACK` is the
environment prefix; the base CloudFormation stack is
`<TXING_AWS_STACK>-aws-base`. The wrapper recipes run plain AWS CLI commands:

- `just aws-town ...`
- `just aws-rig ...`
- `just aws-device ...`

AWS bring-up and destructive rebuild steps live in [aws.md](./aws.md).
Web/admin base stack parameters are initialized separately with
`just aws::deploy-init`; CloudFormation reads the resulting `/txing/stack/*`
SSM Parameter Store values during `aws::deploy`. `just aws::delete` leaves
those manual init parameters in place; `just aws::delete-init` removes only
those final inputs.

## Task Runner

This monorepo uses `just` at the root.

Common commands:

```bash
just --list
just unit::mcu::build
just rig::test
just rig::build
just rig::check <config-dir>
just rig::start <config-dir> true
just rig::stop
just unit::daemon::run
just office::dev
just office::write-env
just aws::deploy
just aws::deploy-town town
just aws::deploy-rig <town-id> raspi server
just aws::deploy-device <rig-id> unit bot
just aws::shadow <thing>
just aws::shadow-reset <thing>
```

Root modules:

- `rig::...` -> generic rig host tooling in `rig/justfile`
- `unit::...` -> current device type tooling in `devices/unit/justfile`
- `aws::...` -> `shared/aws/justfile`
- `office::...` -> `office/justfile`
- `witness::...` -> `witness/justfile`

## Current Named Shadows

Named shadows are selected from the thing's AWS IoT ThingType and the
CloudFormation-managed SSM type catalog under `/txing`.

Current capabilities:

- `town`: `sparkplug`
- `raspi`: `sparkplug`
- `cloud`: `sparkplug`
- `unit`: `sparkplug`, `ble`, `power`, `board`, `mcp`, `video`
- `cloud-mcu`: `sparkplug`, `sqs`, `power`, `ecs`
- `weather`: `sparkplug`, `ble`, `power`, `weather`
- `power`: `sparkplug`, `ble`, `power`

There is no `device` named shadow in the current implementation.

Useful commands:

```bash
just aws::shadow <thing>
just aws::shadow <thing> sparkplug
just aws::shadow-reset <thing>
just aws::shadow-reset <thing> mcp
```

`aws::shadow-reset` deletes the classic unnamed shadow, removes known named
shadows that are not valid for the thing's type catalog capabilities, and
reseeds device named shadows from the default payloads declared in
`devices/<type>/manifest.toml`.

## Common Development Loops

MCU:

```bash
just unit::mcu::check
just unit::mcu::build
just unit::mcu::build-nve-hex unit-test
```

Rig:

```bash
just rig::test
just rig::build
just rig::start <config-dir> true
just rig::log
just rig::stop
```

That source-checkout rig loop is for development. Production `raspi` rig hosts
install GitHub release assets through root-owned `mise` and systemd. Production
`cloud` rigs are updated through `just aws::deploy` and
`just aws::publish latest`. Runtime Lambda updates flow through GitHub
release artifacts plus per-function `publish` recipes or `just aws::publish latest`.

Board:

```bash
just unit::daemon::run
just unit::daemon::test
just unit::daemon::kvs-build-native
just unit::daemon::kvs-test-native
just unit::daemon::kvs-build-trixie
just unit::daemon::hardware-build-native
just unit::daemon::hardware-test-native
just unit::daemon::hardware-build-trixie
```

The Rust unit daemon loads its default config from
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}/daemon.env`
and expects certificate files in the same directory unless explicit certificate
path overrides are supplied. Provision that directory with
`just aws::cert <thing-id>` only when AWS resource changes are
intended; the recipe renders systemd-compatible `daemon.env` content from
`devices/unit/daemon/daemon.env.template` and refuses to overwrite existing
daemon env or certificate material.

The deployed board runtime, MCP/video transport contract, and board install
flow are documented in [components/board.md](./components/board.md).

Office:

```bash
just office::install
just office::write-env
just office::dev
```

Public site:

```bash
cd www
python3 -m http.server 5174
```

Witness:

```bash
just witness::test
```

## Contracts

The current implementation contracts are:

- [Sparkplug lifecycle](./sparkplug-lifecycle.md)
- [Unit thing shadow model](../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../devices/unit/docs/device-rig-shadow-spec.md)
- [Unit board video contract](../devices/unit/docs/board-video.md)
