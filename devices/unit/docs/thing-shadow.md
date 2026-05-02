# Txing Thing Shadow Model

This document defines the current AWS IoT Thing Shadow contract for the `unit` device type.

## Status

- The txing device does not use the classic unnamed shadow.
- Sparkplug MQTT is the source protocol for lifecycle state.
- The `sparkplug` named shadow is an AWS-side materialized Sparkplug view only; it is not intent storage.
- Sparkplug `DCMD.redcon` is the only authoritative external lifecycle command path.
- Shadows are reported-only read models and restart caches; no lifecycle flow uses `state.desired`.

## Named Shadows

Each txing thing uses these named shadows:

- `sparkplug`: witness-owned projection of Sparkplug topic identity, Sparkplug payload facts, and projection metadata.
- `mcu`: rig-owned MCU state under `state.reported.power`, `state.reported.online`, and `state.reported.bleDeviceId`.
- `board`: board-owned board state under `state.reported.power` and `state.reported.wifi`.
- `mcp`: rig-owned mirror of MCP descriptor/status retained topics.
- `video`: board-owned mirror of video descriptor/status retained topics.

Schema/default files live under `devices/unit/aws/`:

- `sparkplug-shadow.schema.json`, `default-sparkplug-shadow.json`
- `mcu-shadow.schema.json`, `default-mcu-shadow.json`
- `board-shadow.schema.json`, `default-board-shadow.json`
- `mcp-shadow.schema.json`, `default-mcp-shadow.json`
- `video-shadow.schema.json`, `default-video-shadow.json`

There is no `device` named shadow. Battery lives in `sparkplug.state.reported.payload.metrics.batteryMv`.

## Sparkplug Projection

Witness writes Sparkplug state into the `sparkplug` named shadow with this shape:

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
          "batteryMv": 3972
        }
      },
      "projection": {
        "observedAt": 1714380001234
      }
    }
  }
}
```

Projection rules:

- `topic` is derived only from the Sparkplug MQTT topic.
- `payload.timestamp` is the Sparkplug payload timestamp when present.
- `payload.seq` is the Sparkplug payload sequence when present.
- `projection.observedAt` is the AWS IoT Rule timestamp.
- `NBIRTH` and `DBIRTH` replace `payload.metrics`.
- `NDATA` and `DDATA` deep-merge changed metric paths into `payload.metrics`.
- `NDEATH` and `DDEATH` replace `payload.metrics` with the actual Sparkplug death payload and still update `topic` plus `projection.observedAt`.
- Node death keeps node metrics such as `redcon=4`, but device death does not. For device lifecycle semantics, readers must treat `topic.messageType = DDEATH` as unavailable and ignore any legacy device metrics that may still appear during rollout.
- Witness does not write the static town shadow.

Metric names preserve Sparkplug structure by splitting both `.` and `/` into nested path segments:

- `redcon` -> `payload.metrics.redcon`
- `batteryMv` -> `payload.metrics.batteryMv`

Town remains a compatibility exception outside witness ownership:

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

## Ownership

- `rig` publishes Sparkplug `NBIRTH`/`NDATA`/`NDEATH`/`DBIRTH`/`DDATA`/`DDEATH`.
- Witness reads Sparkplug MQTT and updates the `sparkplug` named shadow directly.
- `rig` writes the `mcu` and `mcp` named shadows.
- `board` writes the `board` and `video` named shadows.
- Web reads Sparkplug lifecycle state from `namedShadows.sparkplug.state.reported` and publishes lifecycle commands through Sparkplug MQTT `DCMD.redcon`.

## Field Semantics

- Lifecycle semantics are defined canonically in the root [README](../../../README.md).
- `sparkplug.state.reported.topic.messageType` is the last observed Sparkplug message type for that thing.
- `sparkplug.state.reported.payload.metrics.redcon` is the projected Sparkplug readiness metric:
  - valid only for born device states (`DBIRTH` / `DDATA`)
  - `4`: Green / `Cold Camp` / MCU sleep state with BLE presence still online
  - `3`: Yellow / `Torch-Up` / MCU wakeup state with BLE reachability, but MCP unavailable
  - `2`: Orange/Amber / `Ember Watch` / MCU wakeup state with BLE reachability and MCP availability, but retained video status not ready
  - `1`: Red / `Hot Rig` / MCU wakeup state with BLE reachability, MCP availability, and retained video status ready
- `sparkplug.state.reported.topic.messageType = DDEATH` means the rig currently considers the device unavailable and `payload.metrics.redcon` is not defined for that device state.
- `sparkplug.state.reported.payload.metrics.batteryMv` is the latest Sparkplug battery metric.
- `mcu.state.reported.power=true` means the external wakeup state.
- `mcu.state.reported.power=false` means the external sleep state with periodic `5 s` BLE rendezvous wakeups.
- `mcu.state.reported.online` is rig-observed BLE reachability.
- `mcu.state.reported.bleDeviceId` is the last observed BLE identity and fast-reconnect source of truth.
- `board.state.reported.power` is best-effort board power state; stale `true` must not be treated as authoritative after a hard power cut.
- `board.state.reported.wifi.online`, `ipv4`, and `ipv6` are refreshed by the board control loop.
- `mcp.state.reported.descriptor` and `mcp.state.reported.status` mirror retained board MCP MQTT topics.
- `video.state.reported.descriptor` and `video.state.reported.status` mirror retained board video MQTT topics.

## Capability Discovery

`devices/unit/manifest.toml` defines the named shadows supported by the `unit`
device type and points at each shadow schema/default payload. The shared AWS
deploy publishes those type capabilities into SSM leaf parameters under
`/txing/town/raspi/unit`. Runtime and tooling use the thing's AWS IoT ThingType
plus that SSM type catalog to decide which
`$aws/things/<thing>/shadow/name/<shadow>/...` topics to read or reset.

## AWS IoT Note

AWS IoT Thing Shadows do not enforce custom JSON schema automatically. Project code and tests validate payloads before publishing.
