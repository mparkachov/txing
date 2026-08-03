# Documentation

This repository documents the current implementation directly. Historical
design notes have been folded into the owning component guides.

## Start Here

- [Development](./development.md)
- [Installation](./installation.md)
- [Artifacts](./artifacts.md)
- [AWS bring-up and rebuild](./aws.md)
- [AWS Lambda language boundary](./aws-lambda-boundary.md)
- [Future work](./future-work.md)

## Agent Guidance

- [Spec-driven development workflow](./agent-guidance/spec-driven-development.md)
- [Repository editing and operational boundaries](./agent-guidance/editing-boundaries.md)
- [Board operating-system baseline](./components/board.md#operating-system-baseline)

## Component Guides

- [Rig](./components/rig.md)
- [Board](./components/board.md)
- [Board (Debian, frozen)](./components/board-debian-frozen.md)
- [MCU](./components/mcu.md)
- [Office](./components/office.md)
- [Public WWW](./components/www.md)
- [Witness](./components/witness.md)

## Contracts

- [Unit device contracts](./contracts/unit-device-contracts.md)
- [Sparkplug lifecycle](./sparkplug-lifecycle.md)
- [Unit thing shadow model](../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../devices/unit/docs/device-rig-shadow-spec.md)
- [Unit board video contract](../devices/unit/docs/board-video.md)
- [Board video bridge gRPC contract](./contracts/board-video-bridge.md)

## Current Named-Shadow Capabilities

The CloudFormation-managed SSM type catalog under `/txing` declares
capabilities for each AWS IoT ThingType:

- `town`: `sparkplug`
- `raspi`: `sparkplug`
- `cloud`: `sparkplug`
- `local`: `sparkplug`
- `unit`: `sparkplug`, `ble`, `power`, `board`, `mcp`, `video`
- `cyberbrick`: `sparkplug`, `ble`, `power`, `board`, `mcp`, `video`
- `cloud-mcu`: `sparkplug`, `sqs`, `power`, `ecs`
- `weather`: `sparkplug`, `ble`, `power`, `weather`
- `power`: `sparkplug`, `ble`, `power`
- `power-si`: `sparkplug`, `thread`, `power`
- `mac`: `sparkplug`, `power`, `board`, `mcp`, `video`

There is no `device` named shadow in the current implementation.
