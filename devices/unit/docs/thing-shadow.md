# Txing Thing Shadow Model

This document defines the current AWS IoT Thing Shadow contract for the `unit` device type.

## Status

- The unit does not use the classic unnamed shadow.
- Sparkplug MQTT is the source protocol for lifecycle state.
- The `sparkplug` named shadow is an AWS-side materialized Sparkplug view only; it is not intent storage.
- Sparkplug `DCMD.redcon` is the only authoritative external lifecycle command path.
- Shadows are reported-only read models and restart caches; no lifecycle flow uses `state.desired`.

## Named Shadows

Each unit thing uses these named shadows:

- `sparkplug`: witness-owned projection of Sparkplug topic identity, lifecycle metrics, capability availability, and projection metadata.
- `ble`: rig-owned BLE identity/readiness state.
- `power`: rig-owned power capability state, including `state.reported.batteryMv`.
- `board`: board-owned board state under `state.reported.power` and `state.reported.wifi`.
- `mcp`: rig-owned mirror of MCP descriptor/status retained topics.
- `video`: board-owned mirror of video descriptor/status retained topics.

Schema/default files live under `devices/unit/aws/`:

- `sparkplug-shadow.schema.json`, `default-sparkplug-shadow.json`
- `ble-shadow.schema.json`, `default-ble-shadow.json`
- `power-shadow.schema.json`, `default-power-shadow.json`
- `board-shadow.schema.json`, `default-board-shadow.json`
- `mcp-shadow.schema.json`, `default-mcp-shadow.json`
- `video-shadow.schema.json`, `default-video-shadow.json`

There is no active public `mcu` named shadow contract for the upgraded unit. BLE reachability comes from `capability.ble`, wakeup/sleep state comes from Sparkplug `redcon`, and battery telemetry comes from `namedShadows.power.state.reported.batteryMv`.

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

Projection rules:

- `topic` is derived only from the Sparkplug MQTT topic.
- `payload.timestamp` is the Sparkplug payload timestamp when present.
- `payload.seq` is the Sparkplug payload sequence when present.
- `projection.observedAt` is the AWS IoT Rule timestamp.
- Capability-owned named shadows do not carry generic `observedAtMs` or `seq` fields. Readers use AWS IoT Shadow metadata timestamps and root shadow `version` for freshness and ordering.
- `NBIRTH` and `DBIRTH` replace `payload.metrics`.
- `NDATA` and `DDATA` deep-merge changed metric paths into `payload.metrics`.
- `NDEATH` and `DDEATH` replace `payload.metrics` with the actual Sparkplug death payload and still update `topic` plus `projection.observedAt`.
- Device `DDEATH` means unavailable and device `redcon` is not defined.
- Witness does not write the static town shadow.

Metric names preserve Sparkplug structure by splitting both `.` and `/` into nested path segments:

- `redcon` -> `payload.metrics.redcon`
- `capability.ble` -> `payload.metrics.capability.ble`
- `capability.power` -> `payload.metrics.capability.power`

## Ownership

- `rig` publishes Sparkplug `NBIRTH`/`NDATA`/`NDEATH`/`DBIRTH`/`DDATA`/`DDEATH`.
- Witness reads Sparkplug MQTT and updates the `sparkplug` named shadow directly.
- `rig` writes the `ble`, `power`, and `mcp` named shadows.
- `board` writes the `board` and `video` named shadows.
- Web reads lifecycle state from `namedShadows.sparkplug.state.reported` and publishes lifecycle commands through Sparkplug MQTT `DCMD.redcon`.

## Field Semantics

- Lifecycle semantics are defined canonically in the root [README](../../../README.md).
- `sparkplug.state.reported.topic.messageType` is the last observed Sparkplug message type for that thing.
- `sparkplug.state.reported.payload.metrics.redcon` is valid only for born device states (`DBIRTH` / `DDATA`).
- `redcon=4` means sleep state / `Cold Camp`: BLE is reachable and the rest of the unit stack is off.
- `redcon=3` means wakeup state / `Torch-Up`: BLE is reachable and D1 is enabled so the rest of the unit stack can boot.
- `redcon=2` means local board and MCP capability are available.
- `redcon=1` means local board, MCP, and video capability are available.
- `sparkplug.state.reported.topic.messageType = DDEATH` means the rig currently considers the device unavailable and `payload.metrics.redcon` is not defined.
- `sparkplug.state.reported.payload.metrics.capability.ble` is BLE reachability.
- `sparkplug.state.reported.payload.metrics.capability.power` is MCU-controlled wakeup power/D1 availability, not MCU power.
- `power.state.reported.batteryMv` is the latest battery measurement in millivolts.
- `board.state.reported.power` is best-effort board power state; stale `true` must not be treated as authoritative after a hard power cut.
- `board.state.reported.wifi.online`, `ipv4`, and `ipv6` are refreshed by the board control loop.
- `mcp.state.reported.descriptor` and `mcp.state.reported.status` mirror retained board MCP MQTT topics.
- `video.state.reported.descriptor` and `video.state.reported.status` mirror retained board video MQTT topics.
- UI capability indicators should use
  `sparkplug.state.reported.payload.metrics.capability.*` as the reflected
  source of truth. Board/MCP/video REDCON readiness comes from board-owned
  retained v2 capability state consumed by SparkplugManager, not from
  client-side inference.

## Capability Discovery

`devices/unit/manifest.toml` defines the named shadows supported by the `unit` device type and points at each shadow schema/default payload. The shared AWS deploy publishes those type capabilities into SSM leaf parameters under `/txing/town/raspi/unit`. Runtime and tooling use the thing's AWS IoT ThingType plus that SSM type catalog to decide which `$aws/things/<thing>/shadow/name/<shadow>/...` topics to read or reset.

## AWS IoT Note

AWS IoT Thing Shadows do not enforce custom JSON schema automatically. Project code and tests validate payloads before publishing.
