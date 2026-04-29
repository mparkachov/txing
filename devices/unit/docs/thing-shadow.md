# Txing Thing Shadow Model

This document defines the current AWS IoT Thing Shadow contract for the `unit` device type.

## Status

- The txing device no longer uses the classic unnamed shadow.
- Sparkplug MQTT is the source protocol for lifecycle state.
- The `sparkplug` named shadow is an AWS-side materialized Sparkplug view only; it is not intent storage.
- Sparkplug `DCMD.redcon` is the only authoritative external lifecycle command path.
- Shadows are reported-only read models and restart caches; no lifecycle flow uses `state.desired`.
- Video transport remains retained MQTT topics plus board MCP `robot.get_state`; board also mirrors video descriptor/status into the `video` named shadow for readers.

## Named Shadows

Each txing thing uses these named shadows:

- `sparkplug`: witness-owned projection of Sparkplug device state under `state.reported.session` and `state.reported.metrics`.
- `mcu`: rig-owned MCU state under `state.reported.power`, `state.reported.online`, and `state.reported.bleDeviceId`.
- `board`: board-owned board state under `state.reported.power` and `state.reported.wifi`.
- `video`: board-owned mirror of video descriptor/status retained topics.

Schema/default files live under `devices/unit/aws/`:

- `sparkplug-shadow.schema.json`, `default-sparkplug-shadow.json`
- `mcu-shadow.schema.json`, `default-mcu-shadow.json`
- `board-shadow.schema.json`, `default-board-shadow.json`
- `video-shadow.schema.json`, `default-video-shadow.json`

There is no `device` named shadow anymore. Battery now lives in `sparkplug.state.reported.metrics.batteryMv`.

## Sparkplug Projection

Witness writes Sparkplug state into the `sparkplug` named shadow with this shape:

```json
{
  "state": {
    "reported": {
      "session": {
        "entityKind": "device",
        "groupId": "town",
        "edgeNodeId": "rig",
        "deviceId": "unit-local",
        "messageType": "DDATA",
        "online": true,
        "seq": 7,
        "sparkplugTimestamp": 1714380000000,
        "observedAt": 1714380001234
      },
      "metrics": {
        "redcon": 3,
        "batteryMv": 3972,
        "services": {
          "mcp": {
            "available": true
          }
        }
      }
    }
  }
}
```

Projection rules:

- `NBIRTH` and `DBIRTH` replace `metrics` and set `session.online=true`.
- `NDATA` and `DDATA` deep-merge the changed metric paths into `metrics`.
- `NDEATH` and `DDEATH` clear `metrics` to `{}` and set `session.online=false`.
- Witness does not write the static town shadow.

Metric names preserve Sparkplug structure by splitting both `.` and `/` into nested path segments:

- `redcon` -> `metrics.redcon`
- `batteryMv` -> `metrics.batteryMv`
- `services/mcp/available` -> `metrics.services.mcp.available`

## Ownership

- `rig` publishes Sparkplug `NBIRTH`/`NDATA`/`NDEATH`/`DBIRTH`/`DDATA`/`DDEATH`.
- Witness reads Sparkplug MQTT and updates the `sparkplug` named shadow directly.
- `rig` writes the `mcu` named shadow.
- `board` writes the `board` and `video` named shadows.
- Web reads all Sparkplug lifecycle state from `namedShadows.sparkplug.state.reported` and publishes lifecycle commands through Sparkplug MQTT `DCMD.redcon`.

## Field Semantics

- `sparkplug.state.reported.session` describes the last observed Sparkplug lifecycle envelope for that thing.
- `sparkplug.state.reported.metrics.redcon` is the projected Sparkplug readiness metric:
  - `4`: Green / `Cold Camp` / MCU sleep state or BLE unavailable
  - `3`: Yellow / `Torch-Up` / MCU wakeup state with BLE reachability, but MCP unavailable
  - `2`: Orange/Amber / `Ember Watch` / MCU wakeup state with BLE reachability and MCP availability, but retained video status not ready
  - `1`: Red / `Hot Rig` / MCU wakeup state with BLE reachability, MCP availability, and retained video status ready
- `sparkplug.state.reported.metrics.batteryMv` is the latest Sparkplug battery metric.
- `mcu.state.reported.power=true` means the external wakeup state.
- `mcu.state.reported.power=false` means the external sleep state with periodic `5 s` BLE rendezvous wakeups.
- `mcu.state.reported.online` is rig-observed BLE reachability.
- `mcu.state.reported.bleDeviceId` is the last observed BLE identity and fast-reconnect source of truth.
- `board.state.reported.power` is best-effort board power state; stale `true` must not be treated as authoritative after a hard power cut.
- `board.state.reported.wifi.online`, `ipv4`, and `ipv6` are refreshed by the board control loop.
- `video.state.reported.descriptor` and `video.state.reported.status` mirror the retained board video MQTT topics.

## Capability Discovery

`shared/aws/thing-type-capabilities.json` defines the named shadows supported by each thing type. Registration writes the comma-separated `attributes.capabilitiesSet` non-searchable Thing attribute from that definition. Runtime and tooling use `capabilitiesSet` to decide which `$aws/things/<thing>/shadow/name/<shadow>/...` topics to read or reset.

## AWS IoT Note

AWS IoT Thing Shadows do not enforce custom JSON schema automatically. Project code and tests validate payloads before publishing.
