# Documentation

This repository now documents the current implementation directly rather than keeping older phase-design notes as the main reference.

## Start Here

- [Development](./development.md)
- [Installation](./installation.md)
- [AWS bring-up and rebuild](./aws.md)

## Component Guides

- [Rig](./components/rig.md)
- [Board](./components/board.md)
- [MCU](./components/mcu.md)
- [Web](./components/web.md)
- [Witness](./components/witness.md)

## Contracts

- [Sparkplug lifecycle](./sparkplug-lifecycle.md)
- [Unit thing shadow model](../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../devices/unit/docs/device-rig-shadow-spec.md)
- [Unit board video contract](../devices/unit/docs/board-video.md)

## Current Named-Shadow Capabilities

Registration writes `attributes.capabilities` from shared thing definitions
for `town`/`rig` and from each device type manifest:

- `town`: `sparkplug`
- `rig`: `sparkplug`
- `unit`: `sparkplug`, `mcu`, `board`, `mcp`, `video`

There is no `device` named shadow in the current implementation.
