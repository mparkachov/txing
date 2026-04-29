# Txing Rig Contract (Sparkplug + Witness + BLE) v1.3

This document is the integration contract for the rig runtime.

## 1. Scope

Contract between:

- Txing firmware (`mcu/`, BLE peripheral on nRF52840)
- Txing rig runtime (`rig/`, BLE central on Raspberry Pi 5 and Sparkplug lifecycle publisher)
- AWS IoT witness projection (`shared/aws/python/src/aws/sparkplug_witness.py`)
- AWS IoT named Thing Shadows
- AWS IoT MQTT Sparkplug namespace `spBv1.0`

Authoritative schema source:

- `devices/unit/aws/*-shadow.schema.json`

High-level architecture:

- Sparkplug host -> AWS IoT MQTT -> rig -> BLE -> mcu
- rig -> Sparkplug MQTT publication
- witness -> AWS IoT Thing Shadow `sparkplug` projection
- rig -> AWS IoT Thing Shadow `mcu`
- board -> AWS IoT Thing Shadow `board` and `video`

## 2. Ownership

- `rig` is the source of truth for Sparkplug `NBIRTH`/`NDATA`/`NDEATH`/`DBIRTH`/`DDATA`/`DDEATH`.
- Witness is the source of truth for the AWS-side `sparkplug` named shadow.
- `rig` is the source of truth for the `mcu` named shadow.
- `board` is the source of truth for the `board` and `video` named shadows.
- Sparkplug `DCMD.redcon` is the only lifecycle intent input.
- No lifecycle flow uses shadow `desired`.

## 3. Sparkplug Projection Contract

Every rig and device thing exposes a `sparkplug` named shadow with:

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
        "batteryMv": 3795,
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

Field rules:

- `session.entityKind` is `node` for rig things and `device` for txing things.
- `session.groupId` is the Sparkplug group id.
- `session.edgeNodeId` is the Sparkplug edge node id.
- `session.deviceId` exists only for device shadows.
- `session.messageType` is one of `NBIRTH`, `NDATA`, `NDEATH`, `DBIRTH`, `DDATA`, `DDEATH`.
- `session.online` is `true` on birth/data and `false` on death.
- `session.seq` and `session.sparkplugTimestamp` are carried when present in the payload.
- `session.observedAt` is the AWS IoT Rule timestamp.

Metric path rules:

- Witness splits both `.` and `/` into nested metric paths.
- `redcon` -> `metrics.redcon`
- `batteryMv` -> `metrics.batteryMv`
- `services/mcp/available` -> `metrics.services.mcp.available`

Projection rules:

- `NBIRTH` and `DBIRTH` replace `metrics`.
- `NDATA` and `DDATA` deep-merge changed metric paths.
- `NDEATH` and `DDEATH` clear `metrics` to `{}`.

There is no separate `device` named shadow.

## 4. Runtime Shadows

Named shadow ownership outside Sparkplug:

- `mcu.state.reported.power=true` means the external wakeup state.
- `mcu.state.reported.power=false` means the external sleep state with periodic `5 s` rendezvous wakeups.
- `mcu.state.reported.online` is rig-observed BLE reachability.
- `mcu.state.reported.bleDeviceId` is the last observed BLE identity and fast-reconnect source of truth.
- `board.state.reported.*` is board-owned operational state.
- `video.state.reported.*` mirrors the retained board video topics for readers.

Rig uses `mcu`, retained MCP topics, and retained video status to derive the Sparkplug device `redcon` metric that it publishes. Readers query the witness-owned Sparkplug projection instead of subscribing to live Sparkplug traffic directly.

## 5. Sparkplug Topics And Metrics

Namespace and identity:

- Namespace: `spBv1.0`
- Group id: `town`
- Edge node id: `rig`
- Device id: configured txing thing name

Current metrics:

- Node metric: `redcon`
- Device metrics: `redcon`, `batteryMv`
- Device detail metrics: `services/mcp/*`
- Writable device command metric: `redcon`

Current topics:

- `NBIRTH`, `NDATA`, and `NDEATH` for `rig`
- `DBIRTH`, `DDATA`, and `DDEATH` for `txing`
- `DCMD` for txing lifecycle commands

Command semantics:

- Only literal integer `1..4` values for `DCMD.redcon` are accepted.
- `redcon=4` converges toward the MCU sleep state.
- `redcon=1`, `2`, or `3` only require wakeup-state BLE actuation if the MCU is asleep.

## 6. BLE GATT Contract

UUIDs:

- Service `TXING Control`: `f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100`
- Power Command characteristic: `f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100`
- State Report characteristic: `f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100`

Payloads:

- Advertisement manufacturer data:
  - bytes `0..1`: marker `TX`
  - bytes `2..4`: the same 3-byte State Report payload used by GATT
- Power Command (1 byte, write with response):
  - `0x00` -> wakeup state / `power=true`
  - `0x01` -> sleep state / `power=false`
- State Report (3 bytes, read + notify):
  - byte `0`: sleep flag
  - bytes `1..2`: `battery_mv` as little-endian `u16`

State Report sleep-flag values:

- `0x00` -> wakeup state / `power=true`
- `0x01` -> sleep state / `power=false`

## 7. REDCON Semantics

The current implementation uses this txing REDCON ladder:

- `4`
  - MCU is in the sleep state or BLE is unavailable
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

## 8. Restart And Convergence

- Rig restart is conservative and does not recover a pending lifecycle target from shadow.
- Sparkplug shadow state is read-only query state, not intent.
- For `DCMD.redcon=1..3`, rig waits for the next advertisement if disconnected, connects if needed, and writes the wakeup-state command only when `mcu reported.power=false`.
- For `DCMD.redcon=4`, rig waits for `mcu reported.power=false`, then writes the sleep-state command and clears the in-memory target after convergence.
- Unexpected BLE loss emits `DDEATH`; witness projects that to `session.online=false` and `metrics={}`.

## 9. Acceptance Criteria

- From projected `metrics.redcon=4`, sending `DCMD.redcon=3` eventually results in:
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
- `metrics.batteryMv` tracks the latest battery reading published through Sparkplug.
- `mcu.state.reported.online` becomes `true` again after rig observes sustained BLE presence for the configured recovery window.
- `mcu.state.reported.online` becomes `false` only after rig has not observed the device for longer than the presence timeout.
- `DBIRTH` is emitted when `mcu.state.reported.online` becomes `true`.
- `DDEATH` is emitted when `mcu.state.reported.online` becomes `false`.
