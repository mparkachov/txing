# Development

For the system overview, see [../README.md](../README.md). For the documentation map, see [README.md](./README.md).

## Repository Layout

- `devices/unit/`: self-contained current `unit` device type, including MCU, board runtime, rig process implementation, AWS shadow contracts, docs, and web detail adapter
- `rig/`: Python runtime for the always-on rig coordinator
- `web/`: React + Vite admin/operator SPA
- `witness/`: Sparkplug-to-shadow projection Lambda source and tests
- `shared/aws/`: shared AWS CLI helpers, CloudFormation, and registry utilities
- `devices/template/`: scaffold for a new device type using the language-neutral manifest/process/web contracts

## Base Tooling

Repo-wide tooling:

- `uv`
- `just`
- `jq`
- AWS CLI v2 installed from AWS, not from the OS package repository

Host-specific setup, including how each host installs `uv` / `just` and how the
board read-only rootfs is configured, lives in [installation.md](./installation.md).

## Version And Artifact Channels

`VERSION` is the stable release version for the repository. It must stay a base
semantic version such as `0.7.0`.

Runtime builds derive identity from `VERSION` plus Git metadata:

```text
stable release: 0.7.0
feature build:  0.7.0+g<short-sha>
```

Keep the `+g<short-sha>` form for feature and local builds. It is valid SemVer
build metadata and avoids `-`, which is important because the current
Greengrass Lite local recipe path rejects component versions with hyphens.

Use release channels to decide which artifact a host should install; do not
depend on SemVer ordering to decide that `0.7.0+g<short-sha>` is newer than
`0.7.0`. SemVer build metadata does not change precedence, so update tooling
must resolve channels explicitly.

Development direction for installable host tools and board-side native
artifacts:

- `stable` points at the artifact built from the stable `VERSION`, for example `0.7.0`.
- `feature` points at the currently selected artifact from `feature/...` branches, for example `0.7.0+g123456789abc`.
- GitHub release assets should be immutable for each exact artifact version.
- A mutable channel manifest or equivalent `mise` plugin logic should map `stable` and `feature` to exact artifact versions.
- Read-only board boot flows may install `feature` channel artifacts into tmpfs-backed `mise` directories while using the persistent `stable` install as the fallback.
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
just rig::run
just rig::wake
just unit::board::run
just web::dev
just web::write-env
just aws::deploy
just aws::town-deploy town
just aws::rig-deploy <town-id> raspi server
just aws::device-deploy <rig-id> unit bot
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
- `unit`: `sparkplug`, `mcu`, `board`, `mcp`, `video`
- `time`: `sparkplug`, `mcp`, `time`

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
```

Rig:

```bash
just rig::check <rig-id>
just rig::build
just rig::debug
```

Board:

```bash
just unit::board::check
just unit::board::build-native
just unit::board::build
just unit::board::once
```

Web:

```bash
just web::install
just web::write-env
just web::dev
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
