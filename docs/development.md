# Development

For the system overview, see [../README.md](../README.md). For the documentation map, see [README.md](./README.md).

## Repository Layout

- `devices/unit/`: self-contained current `unit` device type, including MCU, board runtime, rig process implementation, AWS shadow contracts, docs, and web detail adapter
- `rig/`: Rust Greengrass components and rig host tooling for the always-on coordinator
- `web/`: React + Vite admin/operator SPA
- `site/`: public static Vite landing page for `thing.dev`
- `witness/`: Sparkplug-to-shadow projection Lambda source and tests
- `shared/aws/`: shared AWS CLI helpers, CloudFormation, and registry utilities
- `devices/template/`: scaffold for a new device type using the language-neutral manifest/process/web contracts

## Base Tooling

Repo-wide tooling:

- `uv`
- `just`
- `jq`
- AWS CLI v2
- GitHub CLI (`gh`) for operator-side stable release deploys

Host-specific setup, including how each host installs `uv` / `just` and how the
board read-only rootfs is configured, lives in [installation.md](./installation.md).

## Version And Artifact Channels

`VERSION` is the stable release version for the repository. It must stay a base
semantic version such as `x.y.z`.

Production Greengrass component versions use `VERSION` exactly. Git SHA and
dirty state are exported separately for diagnostics, but they are not part of
the Greengrass `ComponentVersion`. Create stable releases with the manual
`Txing Stable Release` GitHub Actions workflow from `main` after bumping and
pushing the managed version files yourself. The workflow reads the pushed root
`VERSION`, fails unless it is newer than the latest existing stable `v*` tag,
publishes the GitHub Release, and also publishes the rig stable binaries. It
does not commit or push version changes back to `main`.

Stable rigs do not pull the repository and do not run AWS CLI. After a stable
release workflow finishes, the operator Mac publishes the release artifacts to
Greengrass with:

```bash
just rig::deploy-release latest all
```

Development direction for installable host tools and board-side native
artifacts:

- `stable` points at the artifact built from the stable `VERSION`, for example `x.y.z`.
- `feature` points at explicitly named debug artifacts and must not be confused with production Greengrass component versions.
- GitHub release assets should be immutable for each exact artifact version.
- The unit daemon uses mise's GitHub backend directly; stable rig components are
  published to Greengrass from GitHub release assets; see
  [artifacts.md](./artifacts.md).
- Unit daemon feature prereleases are published by the manual `Unit Daemon
  Feature Prerelease` GitHub Actions workflow from pushed `feature/*` branches.
- Read-only board boot flows may install `feature` channel artifacts into
  tmpfs-backed `mise` directories while using the persistent `stable` install as
  the fallback.
- Writable maintenance flows should update the persistent baseline with the `stable` channel.

## Project-Local AWS Config

The default workflow keeps AWS config in the checkout:

```bash
cp config/aws.env.example config/aws.env
cp config/aws.credentials.example config/aws.credentials
```

Profile wrappers:

- `just aws-town ...`
- `just aws-rig ...`
- `just aws-device ...`

AWS bring-up and destructive rebuild steps live in [aws.md](./aws.md).

## Task Runner

This monorepo uses `just` at the root.

Common commands:

```bash
just --list
just unit::mcu::build
just rig::check <rig-id>
just rig::deploy
just rig::status <rig-id>
just unit::daemon::run
just unit::board::run
just web::dev
just web::write-env
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
- `web::...` -> `web/justfile`
- `witness::...` -> `witness/justfile`

## Current Named Shadows

Named shadows are selected from the thing's AWS IoT ThingType and the
CloudFormation-managed SSM type catalog under `/txing`.

Current capabilities:

- `town`: `sparkplug`
- `raspi`: `sparkplug`
- `cloud`: `sparkplug`
- `unit`: `sparkplug`, `ble`, `power`, `board`, `mcp`, `video`
- `time`: `sparkplug`, `mcp`, `time`
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
just rig::check <rig-id>
just rig::build
just rig::deploy
just rig::log <rig-id>
```

That source-checkout rig loop is for development and admin builder use. Stable
rig hosts receive Greengrass deployments published from the operator machine
instead.

Board:

```bash
just unit::daemon::run
just unit::board::check
just unit::board::build-native
just unit::board::build
just unit::board::once
```

The Rust unit daemon loads its default config from
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}/.env`
and expects certificate files in the same directory unless explicit certificate
path overrides are supplied. Provision that directory with
`just unit::daemon::cert <thing-id>` only when AWS resource changes are
intended; the recipe writes sourceable `.env` content and refuses to overwrite
existing daemon env or certificate material.

Web:

```bash
just web::install
just web::write-env
just web::dev
```

Public site:

```bash
cd site
bun install
bun run dev
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
