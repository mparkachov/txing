# Txing Rig Contract (Sparkplug + Witness + BLE) v2.0

This document is the integration contract for the current unit rig runtime.

## Scope

Contract between:

- Unit firmware (`mcu/`, BLE peripheral on XIAO nRF54L15)
- Rig runtime (`rig/`, BLE central on Raspberry Pi 5 and Sparkplug lifecycle publisher)
- AWS IoT witness projection (`witness/`)
- AWS IoT named Thing Shadows
- AWS IoT MQTT Sparkplug namespace `spBv1.0`

Authoritative schema source:

- `devices/unit/aws/*-shadow.schema.json`

## Ownership

- `rig` is the source of truth for Sparkplug `NBIRTH`/`NDATA`/`NDEATH`/`DBIRTH`/`DDATA`/`DDEATH`.
- Witness is the source of truth for the AWS-side `sparkplug` named shadow on rig and unit things.
- `dev.txing.rig.BleConnectivity` is the source of truth for the `ble` and `power` named shadows.
- `rig` is the source of truth for the `mcp` named shadow.
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
          "capability": {
            "sparkplug": true,
            "ble": true,
            "power": true,
            "board": false,
            "mcp": false,
            "video": false
          }
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
- `capability.ble` -> `payload.metrics.capability.ble`
- `capability.power` -> `payload.metrics.capability.power`

Capability availability:

- The thing type capability list defines the full public availability surface for a device.
- SparkplugManager reflects every capability from the thing's comma-separated `capabilities` attribute as a boolean metric named `capability.<name>`.
- `true` means the corresponding named shadow or data domain is active and current enough for logic to use.
- `false` means that domain is stale and must not be used, even if older data remains in the corresponding named shadow.
- On startup and inventory refresh, non-`sparkplug` capabilities initialize to `false` until fresh adapter state reports them available.

Projection rules:

- `NBIRTH` and `DBIRTH` replace `payload.metrics`.
- `NDATA` and `DDATA` deep-merge changed metric paths.
- `NDEATH` and `DDEATH` replace `payload.metrics` with the actual death payload while still updating `topic` and `projection`.
- Device `DDEATH` means unavailable; device `redcon` is valid only for `DBIRTH` / `DDATA`.

There is no separate `device` named shadow.

## Runtime Shadows

Named shadow ownership outside Sparkplug:

- `ble.state.reported.bleAddress` is the last observed BLE address.
- `ble.state.reported.bleLocalName` is the BLE local name from the factory/NVE Thing ID record.
- `power.state.reported.batteryMv` is the latest battery measurement in millivolts.
- `board.state.reported.*` is board-owned operational state.
- `mcp.state.reported.*` mirrors the retained board MCP topics for readers.
- `video.state.reported.*` mirrors the retained board video topics for readers.
- Capability-owned named shadows contain only domain fields. Generic bookkeeping such as `observedAtMs` and `seq` must not be published there; readers use AWS IoT Shadow metadata timestamps and the root shadow `version` for freshness and ordering.

Rig uses BLE v2 power-profile samples to publish Sparkplug device `redcon` and `capability.*` metrics. Readers query the witness-owned Sparkplug projection instead of subscribing to live Sparkplug traffic directly.

## Sparkplug Topics And Metrics

Namespace and identity:

- Namespace: `spBv1.0`
- Group id: `town`
- Edge node id: `rig`
- Device id: configured unit thing name

Current metrics:

- Node metrics: `bdSeq`, `redcon`
- Device metrics: `redcon` and `capability.*`
- Deprecated availability/lifecycle helpers such as `bleConnected`, `mcpAvailable`, and `mode` must not be published as Sparkplug metrics; use `capability.*` and `redcon` instead
- Battery belongs in the `power` named shadow
- Board, MCP, and video state belongs in the corresponding capability-owned named shadows
- Writable device command metric: `redcon`

Current topics:

- `NBIRTH`, `NDATA`, and `NDEATH` for `rig`
- `DBIRTH`, `DDATA`, and `DDEATH` for units
- `DCMD` for unit lifecycle commands

## REDCON Semantics

The root [README](../../../README.md) is the canonical lifecycle contract. In brief:

- `DDEATH` means the device is unavailable because BLE is not reachable.
- `DBIRTH` / `DDATA` with `redcon=4` means the device is alive and parked in the sleep state.
- `DBIRTH` / `DDATA` with `redcon=3` means the unit stack power enable is active.

Current commandable REDCON levels for the upgraded unit are `[4, 3, 2, 1]`.

The unit REDCON rules are declared ahead of the board/MCP/video v2 capability rollout:

- `4 = ["sparkplug", "ble"]`
- `3 = ["sparkplug", "ble", "power"]`
- `2 = ["sparkplug", "ble", "power", "board", "mcp"]`
- `1 = ["sparkplug", "ble", "power", "board", "mcp", "video"]`

Until board/MCP/video publish v2 capability state, current unit devices naturally converge only to REDCON `4` or `3`. Board shadows may still exist and be read, but they do not drive REDCON until the v2 capability states are published.

## Acceptance Criteria

- From projected `payload.metrics.redcon=4`, sending `DCMD.redcon=3` eventually results in:
  - a BLE connection during a rendezvous window
  - a successful REDCON 3 command write
  - a State Report confirmation
  - D1 enabled by the MCU
  - `power.state.reported.batteryMv` refreshed when the firmware reports battery
  - Sparkplug `capability.power=true`
  - the in-memory pending REDCON target cleared once actual Sparkplug `redcon <= 3`
- From projected `payload.metrics.redcon=3`, sending `DCMD.redcon=4` eventually results in:
  - a successful REDCON 4 command write
  - D1 disabled by the MCU
  - published Sparkplug `redcon=4`
  - Sparkplug `capability.power=false`
  - the in-memory pending REDCON target cleared on convergence
- `DBIRTH` is emitted when BLE capability becomes reachable.
- `DDEATH` is emitted when BLE capability becomes unreachable.
