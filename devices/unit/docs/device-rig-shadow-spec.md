# Txing Rig Contract (Sparkplug + Witness + BLE) v1.4

This document is the integration contract for the rig runtime.

## Scope

Contract between:

- Txing firmware (`mcu/`, BLE peripheral on nRF52840)
- Txing rig runtime (`rig/`, BLE central on Raspberry Pi 5 and Sparkplug lifecycle publisher)
- AWS IoT witness projection (`witness/src/witness/sparkplug_witness.py`)
- AWS IoT named Thing Shadows
- AWS IoT MQTT Sparkplug namespace `spBv1.0`

Authoritative schema source:

- `devices/unit/aws/*-shadow.schema.json`

## Ownership

- `rig` is the source of truth for Sparkplug `NBIRTH`/`NDATA`/`NDEATH`/`DBIRTH`/`DDATA`/`DDEATH`.
- Witness is the source of truth for the AWS-side `sparkplug` named shadow on rig and unit things.
- `rig` is the source of truth for the `mcu` and `mcp` named shadows.
- `board` is the source of truth for the `board` and `video` named shadows.
- Sparkplug `DCMD.redcon` is the only lifecycle intent input.
- No lifecycle flow uses shadow `desired`.

## Sparkplug Projection Contract

Every rig and device thing exposes a witness-owned `sparkplug` named shadow with:

```json
{
  "state": {
    "reported": {
      "topic": {
        "namespace": "spBv1.0",
        "groupId": "town",
        "messageType": "DDATA",
        "edgeNodeId": "rig",
        "deviceId": "unit-local"
      },
      "payload": {
        "timestamp": 1714380000000,
        "seq": 7,
        "metrics": {
          "redcon": 3,
          "batteryMv": 3795
        }
      },
      "projection": {
        "observedAt": 1714380001234
      }
    }
  }
}
```

Field rules:

- `reported.topic` comes only from the Sparkplug MQTT topic.
- `reported.topic.messageType` is one of `NBIRTH`, `NDATA`, `NDEATH`, `DBIRTH`, `DDATA`, `DDEATH`.
- `reported.topic.deviceId` exists only for device shadows.
- `reported.payload.timestamp` and `reported.payload.seq` are preserved only when present in the Sparkplug payload.
- `reported.projection.observedAt` is the AWS IoT Rule timestamp.
- `reported.payload.metrics` is the materialized Sparkplug metric object.

Metric path rules:

- Witness splits both `.` and `/` into nested metric paths.
- `redcon` -> `payload.metrics.redcon`
- `batteryMv` -> `payload.metrics.batteryMv`

Projection rules:

- `NBIRTH` and `DBIRTH` replace `payload.metrics`.
- `NDATA` and `DDATA` deep-merge changed metric paths.
- `NDEATH` and `DDEATH` replace `payload.metrics` with the actual death payload while still updating `topic` and `projection`.
- Node death keeps node metrics such as `redcon=4`, but device death does not. Device lifecycle semantics are defined canonically in the root [README](../../../README.md): device `DDEATH` means unavailable, while device `redcon` is valid only for `DBIRTH` / `DDATA`.

There is no separate `device` named shadow.

Town keeps a compatibility-only `sparkplug` shadow outside witness ownership with:

```json
{
  "state": {
    "reported": {
      "payload": {
        "metrics": {
          "redcon": 1
        }
      }
    }
  }
}
```

## Runtime Shadows

Named shadow ownership outside Sparkplug:

- `mcu.state.reported.power=true` means the external wakeup state.
- `mcu.state.reported.power=false` means the external sleep state with periodic `5 s` rendezvous wakeups.
- `mcu.state.reported.online` is rig-observed BLE reachability.
- `mcu.state.reported.bleDeviceId` is the last observed BLE identity and fast-reconnect source of truth.
- `board.state.reported.*` is board-owned operational state.
- `mcp.state.reported.*` mirrors the retained board MCP topics for readers.
- `video.state.reported.*` mirrors the retained board video topics for readers.

Rig uses `mcu`, retained MCP topics, and retained video status to derive the Sparkplug device `redcon` metric that it publishes. Readers query the witness-owned Sparkplug projection instead of subscribing to live Sparkplug traffic directly.

## Sparkplug Topics And Metrics

Namespace and identity:

- Namespace: `spBv1.0`
- Group id: `town`
- Edge node id: `rig`
- Device id: configured txing thing name

Current metrics:

- Node metrics: `bdSeq`, `redcon`
- Device metrics: `redcon`, `batteryMv`
- Writable device command metric: `redcon`

Current topics:

- `NBIRTH`, `NDATA`, and `NDEATH` for `rig`
- `DBIRTH`, `DDATA`, and `DDEATH` for `txing`
- `DCMD` for txing lifecycle commands

## REDCON Semantics

The root [README](../../../README.md) is the canonical lifecycle contract. In brief:

- `DDEATH` means the device is unavailable because the rig currently considers `mcu.state.reported.online=false`.
- `DBIRTH` / `DDATA` with `redcon=4` means the device is still alive and parked in the sleep state.

The born-state REDCON ladder is:

- `4`
  - MCU is in the sleep state
  - BLE presence is still online through the rendezvous advertisements
- `3`
  - BLE is reachable
  - MCU is in the wakeup state
  - MCP is not yet available
- `2`
  - BLE is reachable
  - MCU is in the wakeup state
  - MCP is available
  - retained video status is not yet ready
- `1`
  - BLE is reachable
  - MCU is in the wakeup state
  - MCP is available
  - retained video status is ready and fresh

Rig publishes these metrics into Sparkplug. Witness then materializes them into the `sparkplug` named shadow.

## Acceptance Criteria

- From projected `payload.metrics.redcon=4`, sending `DCMD.redcon=3` eventually results in:
  - a BLE connection during a rendezvous window
  - a successful wakeup-state command write
  - a State Report confirmation
  - `mcu.state.reported.power=true`
  - the in-memory pending REDCON target cleared once actual Sparkplug `redcon <= 3`
- From `mcu.state.reported.power=true`, sending `DCMD.redcon=4` eventually results in:
  - a successful sleep-state command write
  - `mcu.state.reported.power=false`
  - published Sparkplug `redcon=4`
  - the in-memory pending REDCON target cleared on convergence
- `payload.metrics.batteryMv` tracks the latest battery reading published through Sparkplug.
- `DBIRTH` is emitted when `mcu.state.reported.online` becomes `true`.
- `DDEATH` is emitted when `mcu.state.reported.online` becomes `false`.
