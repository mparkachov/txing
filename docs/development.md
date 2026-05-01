# Development

For the system overview, see [../README.md](../README.md). For the documentation map, see [README.md](./README.md).

## Repository Layout

- `devices/unit/mcu/`: Rust firmware for the current `unit` watch layer
- `devices/unit/board/`: Python runtime for the device-side Raspberry Pi board
- `rig/`: Python runtime for the always-on rig coordinator
- `web/`: React + Vite admin/operator SPA
- `witness/`: Sparkplug-to-shadow projection Lambda stack
- `shared/aws/`: shared AWS CLI helpers, CloudFormation, and registry utilities
- `devices/unit/aws/`: named-shadow schemas and default payloads for `unit`
- `devices/unit/docs/`: unit-specific contracts

## Base Tooling

Repo-wide tooling:

- `uv`
- `just`
- `jq`
- `aws`

Host-specific setup, including board read-only rootfs, lives in [installation.md](./installation.md).

## Project-Local AWS Config

The default workflow keeps AWS config in the checkout:

```bash
cp config/aws.env.example config/aws.env
cp config/aws.credentials.example config/aws.credentials
cp config/aws.config.example config/aws.config
cp config/rig.env.example config/rig.env
cp config/board.env.example config/board.env
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
just mcu::build
just rig::run
just rig::wake
just board::run
just web::dev
just web::write-env
just witness::deploy
just aws::shadow <thing>
just aws::shadow-reset <thing>
```

Root modules:

- `rig::...` -> `rig/justfile`
- `board::...` -> `devices/unit/board/justfile`
- `aws::...` -> `shared/aws/justfile`
- `mcu::...` -> `devices/unit/mcu/justfile`
- `web::...` -> `web/justfile`
- `witness::...` -> `witness/justfile`

## Current Named Shadows

Named shadows are selected from `attributes.capabilitiesSet`.

Current capabilities:

- `town`: `sparkplug`
- `rig`: `sparkplug`
- `unit`: `sparkplug`, `mcu`, `board`, `mcp`, `video`

There is no `device` named shadow in the current implementation.

Useful commands:

```bash
just aws::shadow <thing>
just aws::shadow <thing> sparkplug
just aws::shadow-reset <thing>
just aws::shadow-reset <thing> mcp
```

`aws::shadow-reset` deletes the classic unnamed shadow, removes known named shadows that are not valid for the thing's current `capabilitiesSet`, and reseeds the valid named shadows from `devices/<type>/aws/default-<shadow>-shadow.json`.

## Common Development Loops

MCU:

```bash
just mcu::check
just mcu::build
```

Rig:

```bash
just rig::check
just rig::build
just rig::debug
```

Board:

```bash
just board::check
just board::build-native
just board::build
just board::once
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
just witness::deploy
```

## Contracts

The current implementation contracts are:

- [Sparkplug lifecycle](./sparkplug-lifecycle.md)
- [Unit thing shadow model](../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../devices/unit/docs/device-rig-shadow-spec.md)
- [Unit board video contract](../devices/unit/docs/board-video.md)
