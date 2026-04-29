# Sparkplug Lifecycle

## Status

- Scope: current lifecycle control through Sparkplug with one writable metric: `redcon`
- Group model: `town` is the Sparkplug group id
- Edge model: `rig` is the Sparkplug edge node
- Device model: each physical `txing` is one Sparkplug device and one AWS IoT thing
- Sparkplug MQTT is the source protocol
- The `sparkplug` named shadow is the AWS-side materialized Sparkplug view, not device intent storage
- `DCMD.redcon` is the only writable lifecycle command path

## Current Decisions

- Sparkplug is the only authoritative lifecycle intent transport.
- The `sparkplug` named shadow is a queryable AWS projection of actual Sparkplug state.
- The current UI stays simple: one on/off switch and one `Connect` / `Disconnect` button.
- UI lifecycle mapping is:
  - `on` -> request `redcon=3`
  - `off` -> request `redcon=4`
- Users do not directly select REDCON levels.
- `mcu.*`, `board.*`, and `video.*` remain AWS shadow detail only.
- The current implementation derives txing REDCON from BLE reachability, MCU wake state, MCP availability, and board video readiness.

## Identity Model

- `town`
  - Sparkplug group id
  - plain Sparkplug/MQTT identifier only
  - static compatibility shadow uses `session.entityKind=group`
- `rig`
  - Sparkplug edge node id
  - dynamic AWS IoT thing group name for assigned txings
  - node lifecycle uses `NBIRTH`/`NDATA`/`NDEATH`
  - node metrics such as `redcon` project into `metrics.redcon`
- `txing`
  - Sparkplug device id
  - each physical txing has its own AWS IoT thing
  - Sparkplug device id is the txing AWS IoT thing name
  - `txing` means the full physical device, including MCU and board together

## High-Level Architecture

```text
Sparkplug host
  -> sends DCMD.redcon to rig for a specific txing

rig
  -> owns lifecycle convergence and Sparkplug publication
  -> publishes NBIRTH/NDATA/NDEATH for the rig node
  -> publishes DBIRTH/DDATA/DDEATH for txing devices

AWS IoT witness
  -> reads Sparkplug MQTT topics
  -> resolves rig things from registry search
  -> updates sparkplug named shadows directly

txing board control
  -> remains owner of board power and wifi shadow fields
  -> publishes retained board video descriptor/status topics for rig

txing gateway / BLE path
  -> remains owner of mcu reported.*
  -> determines BLE reachability for DBIRTH/DDEATH
```

## Authority and Ownership

- Sparkplug is the only authoritative lifecycle intent path.
- AWS shadow is reflection and durable restart cache only.
- `rig` is the only authority that publishes Sparkplug lifecycle state for rig and txing entities.
- Witness is the only authority that writes the AWS-side `sparkplug` named shadow projection.
- `board` remains the source of truth for board power and wifi operational state.
- `rig` remains the source of truth for `mcu reported.*`.
- `mcu.*`, `board.*`, and `video.*` are not the public lifecycle control API.

## Sparkplug Contract

### Node Metrics

Rig node lifecycle uses `NBIRTH`, `NDATA`, and `NDEATH`.

- `NBIRTH`
  - carries `bdSeq`
  - carries `redcon=1`
- `NDATA`
  - carries incremental node metric changes when present
- `NDEATH`
  - carries the matching `bdSeq`

Meaning:

- if the rig lifecycle service is up and operating, node `metrics.redcon=1`

### Device Metrics

Each txing device currently publishes these lifecycle metrics:

- `redcon`
- `batteryMv`
- `services/mcp/*`

### Commands

The current implementation accepts exactly one writable lifecycle command:

- `DCMD.redcon`
  - integer literal values `1..4`

## Shadow Projection Model

### Sparkplug Named Shadow

Witness materializes Sparkplug into `namedShadows.sparkplug.state.reported` with:

- `session`
  - `entityKind`
  - `groupId`
  - `edgeNodeId`
  - optional `deviceId`
  - `messageType`
  - `online`
  - optional `seq`
  - optional `sparkplugTimestamp`
  - `observedAt`
- `metrics`
  - nested metric object built from Sparkplug metric names

Metric path rules:

- split both `.` and `/` into nested object path segments
- `redcon` -> `metrics.redcon`
- `batteryMv` -> `metrics.batteryMv`
- `services/mcp/available` -> `metrics.services.mcp.available`

Projection behavior:

- `NBIRTH` and `DBIRTH`
  - replace `metrics`
  - set `session.online=true`
- `NDATA` and `DDATA`
  - deep-merge changed metrics into existing `metrics`
  - preserve omitted metrics
- `NDEATH` and `DDEATH`
  - clear `metrics` to `{}`
  - set `session.online=false`

Example projected txing shadow:

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
        "online": true
      },
      "metrics": {
        "redcon": 2,
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

### Rig And Town Projection

- rig things have their own `sparkplug` named shadow and receive witness-owned node projections
- town keeps a static compatibility `sparkplug` shadow using the same schema:
  - `session.entityKind=group`
  - `session.online=true`
  - `metrics.redcon=1`

## Current REDCON Semantics

The current implementation uses this txing REDCON ladder:

- `REDCON 4`
  - MCU is in the sleep state or BLE is unavailable
- `REDCON 3`
  - BLE is reachable
  - MCU is in the wakeup state
  - MCP is not yet available
- `REDCON 2`
  - BLE is reachable
  - MCU is in the wakeup state
  - MCP is available
  - retained video status is not yet ready
- `REDCON 1`
  - BLE is reachable
  - MCU is in the wakeup state
  - MCP is available
  - retained video status is ready and fresh

## Convergence Behavior

Rig receives target REDCON only through Sparkplug.

- target `redcon=4`
  - converge txing to the sleep state
  - publish Sparkplug device `redcon=4`
  - clear the in-memory pending REDCON target on convergence
- target `redcon=3`
  - wake txing
  - once MCU is awake, publish Sparkplug device `redcon=3`
  - if MCP/video conditions later satisfy higher derived levels, actual REDCON may rise naturally to `2` or `1`
  - clear the in-memory pending REDCON target once actual REDCON reaches the commanded REDCON

The current implementation keeps the derived-behavior model rather than making REDCON a strict actuator state machine.

## Birth and Death Rules

### NBIRTH / NDATA / NDEATH

Rig publishes Sparkplug node lifecycle as a proper `NBIRTH` / `NDATA` / `NDEATH` stream:

- `NBIRTH` carries `bdSeq` and `redcon=1`
- `NDATA` carries incremental node metrics when needed
- `NDEATH` carries the matching `bdSeq`

### DBIRTH

Txing emits `DBIRTH` when the device is BLE-reachable.

### DDEATH

Txing emits `DDEATH` only for unexpected device loss on the same reachability timeout that currently drives `ble.online=false`.

Intentional GUI-off / `REDCON 4` sleep does not emit `DDEATH`. In that case the rig keeps publishing normal device lifecycle state and only reflects `mcu reported.online=false` once BLE presence ages out.

On unexpected-loss `DDEATH`, rig should:

- publish Sparkplug device `redcon=4`
- clear any in-memory pending REDCON target

The witness projection then clears `metrics` and marks `session.online=false`.

## Restart Behavior

Rig restart should be conservative:

- start from current `mcu`, `board`, `video`, and Sparkplug-derived in-memory observations
- do not recover a persisted lifecycle target from shadow
- do not treat the Sparkplug named shadow as command state

Any pending lifecycle target after restart must come from a fresh Sparkplug command, not from shadow state.

## UI Behavior

UI behavior stays intentionally simple:

- the user has one on/off switch
- the user has one `Connect` / `Disconnect` button
- the user does not select REDCON levels directly
- the `Connect` button is enabled only when the primary displayed REDCON is `1`

Lifecycle mapping:

- UI `on` -> Sparkplug intent `redcon=3`
- UI `off` -> Sparkplug intent `redcon=4`

The browser reads lifecycle state only from the `sparkplug` named shadow projection and does not write `state.desired`.

## Boundaries

The current implementation includes:

- Sparkplug lifecycle command transport
- one writable Sparkplug metric: `redcon`
- Sparkplug lifecycle reporting for rig and txing
- witness-owned AWS shadow projection of actual lifecycle state
- continued use of current `mcu.*`, `board.*`, and `video.*` operational detail

The current implementation does not include:

- additional writable Sparkplug lifecycle metrics beyond txing `redcon`
- town lifecycle management through Sparkplug
- direct shadow lifecycle control as an authoritative path
- user-facing REDCON selection in UI
- mobility or automatic handoff between rigs
