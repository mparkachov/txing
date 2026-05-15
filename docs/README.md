# Documentation

This repository now documents the current implementation directly rather than keeping older phase-design notes as the main reference.

## Start Here

- [Development](./development.md)
- [Installation](./installation.md)
- [AWS bring-up and rebuild](./aws.md)
- [Feature mise release architecture](./feature-mise.md)
- [Feature mise phase 1 manual runbook](./feature-mise-impl.md)
- [Future work](./future-work.md)

## Component Guides

- [Rig](./components/rig.md)
- [Board](./components/board.md)
- [MCU](./components/mcu.md)
- [Web](./components/web.md)
- [Public Site](./components/site.md)
- [Witness](./components/witness.md)

## Contracts

- [Sparkplug lifecycle](./sparkplug-lifecycle.md)
- [Unit thing shadow model](../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../devices/unit/docs/device-rig-shadow-spec.md)
- [Unit board video contract](../devices/unit/docs/board-video.md)

## Current Named-Shadow Capabilities

The CloudFormation-managed SSM type catalog under `/txing` declares
capabilities for each AWS IoT ThingType:

- `town`: `sparkplug`
- `raspi`: `sparkplug`
- `cloud`: `sparkplug`
- `unit`: `sparkplug`, `ble`, `power`, `board`, `mcp`, `video`
- `time`: `sparkplug`, `mcp`, `time`
- `weather`: `sparkplug`, `ble`, `power`, `weather`
- `power`: `sparkplug`, `ble`, `power`

There is no `device` named shadow in the current implementation.
