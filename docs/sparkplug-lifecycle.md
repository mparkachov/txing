# Sparkplug Lifecycle

## Status

- Scope: current lifecycle control through Sparkplug with one writable metric: `redcon`
- Goal: move lifecycle authority from AWS shadow power fields to Sparkplug while preserving current operational behavior
- Group model: `town` is the Sparkplug group id
- Edge model: `rig` is the Sparkplug edge node
- Device model: each physical `txing` is one Sparkplug device and one AWS IoT thing
- Shadow role: reflection and restart cache only, not the authoritative intent transport
- Registry role: `attributes.rig` and `attributes.bleDeviceId` carry stable per-txing rig assignment and BLE reconnect metadata

## Current Decisions

- Sparkplug is the only authoritative lifecycle intent transport.
- `DCMD.redcon` is the only writable lifecycle command.
- The current UI stays simple: one on/off switch and one `Connect` / `Disconnect` button.
- UI lifecycle mapping is:
  - `on` -> request `redcon=3`
  - `off` -> request `redcon=4`
- Users do not directly select REDCON levels.
- `mcu.*` and `board.*` remain in shadow as supporting operational detail only.
- The current implementation derives txing REDCON from BLE reachability, MCU wake state, MCP availability, and board video readiness.

## Identity Model

- `town`
  - Sparkplug group id
  - plain Sparkplug/MQTT identifier only
- `rig`
  - Sparkplug edge node id
  - dynamic AWS IoT thing group name for assigned txings
  - node lifecycle uses `NBIRTH/NDEATH`
  - `rig.redcon` is a Sparkplug node metric carried by `NBIRTH`
- `txing`
  - Sparkplug device id
  - each physical txing has its own AWS IoT thing/shadow
  - Sparkplug device id is the txing AWS IoT thing name
  - `txing` means the full physical device, including MCU and board together

Future mobility between rigs is intentionally deferred, but the per-txing identity is already independent from the rig identity.

## High-Level Architecture

```text
Sparkplug host
  -> sends DCMD.redcon to rig for a specific txing

rig
  -> owns lifecycle intent and lifecycle convergence
  -> publishes NBIRTH/NDEATH for the rig node; NBIRTH carries rig.redcon
  -> publishes DBIRTH/DDATA/DDEATH for txing devices
  -> reflects reported-only lifecycle state into txing AWS shadows only
  -> derives txing sparkplug reported.redcon from BLE reachability plus retained MCP/video readiness inputs

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
- `rig` is the only authority that computes `txing` sparkplug named-shadow `state.reported.redcon`.
- `board` remains the source of truth for board power and wifi operational state.
- `rig` remains the source of truth for `mcu reported.*`.
- `mcu.*` and `board.*` are not the intended public lifecycle control API.

## Sparkplug Contract

### Node Metrics

The current implementation publishes rig node lifecycle through `NBIRTH/NDEATH`.

`rig.redcon` is a Sparkplug node metric published through `NBIRTH`.

Node birth/death uses Sparkplug `bdSeq`:

- `NBIRTH`
  - carries `bdSeq`
  - carries `rig.redcon=1`
- `NDEATH`
  - carries the matching `bdSeq`

Meaning:

- if the rig lifecycle service is up and operating, `rig.redcon=1`

Rig REDCON is independent from child txing REDCON values.
The current implementation does not add node `NDATA`.

### Device Metrics

Each txing device publishes exactly these Sparkplug lifecycle metrics:

- `redcon`
- `batteryMv`

### Commands

The current implementation accepts exactly one writable lifecycle command:

- `DCMD.redcon`
  - integer literal values `1..4`

Current UI mapping:

- UI `on` sends intent equivalent to `DCMD.redcon=3`
- UI `off` sends intent equivalent to `DCMD.redcon=4`

## Shadow Reflection Model

### Txing Shadow

Txing shadow keeps:

- `sparkplug.state.reported.redcon`
- `state.device reported.batteryMv`
- supporting `mcu reported.*`
- supporting `reported.*`

Semantics:

- `sparkplug.state.reported.redcon`
  - reflects the actual lifecycle state of txing
  - must match the Sparkplug device actual REDCON
- `state.device reported.batteryMv`
  - reflects the actual lifecycle battery metric of txing
  - must match the Sparkplug device actual `batteryMv`
- Direct scalar attributes under `txing.state.reported` are the strict Sparkplug metric reflection surface.
  - In the current implementation the only top-level lifecycle reflection metric is `redcon`.
  - `batteryMv` now lives under `device reported.batteryMv`.
  - Sparkplug device metrics also include `services/mcp/*` as the MCP discovery summary (availability, transport, descriptor topic, lease settings, and server/protocol versions).
  - `device.mcu.*` and `device.board.*` remain shadow-only operational detail and are not alternate top-level Sparkplug metric reflections.
- AWS IoT registry attributes hold stable per-device metadata outside the shadow:
  - `attributes.name`
  - `attributes.shortId`
  - `attributes.rig`
  - `attributes.town`
  - `attributes.bleDeviceId`
- The searchable/indexed subset is narrower:
  - `attributes.name` on all thing types
  - `attributes.town` on `rig` and device things
  - `attributes.rig` on device things
  - `attributes.shortId` and `attributes.bleDeviceId` remain metadata only

Example reflected txing shadow shape:

```json
{
  "state": {
    "reported": {
      "redcon": 2,
      "device": {
        "batteryMv": 3972,
        "mcu": {
          "power": true
        },
        "board": {
          "power": true,
          "wifi": {
            "online": true
          }
        }
      }
    }
  }
}
```

### Rig And Town Reflection

The current implementation maintains first-class AWS IoT things and reported-only shadows for `rig` and `town`.

- `rig.redcon=1` is published in `NBIRTH` and written into the rig shadow directly by the rig runtime.
- `rig.redcon=4` is best-effort written on graceful `NDEATH` by the rig runtime.
- `town.redcon=1` is currently static in the town shadow.
- Town membership comes from rig things with `thingTypeName=rig` and searchable `attributes.town`.
- Device membership still comes from the dynamic AWS IoT thing group whose name matches `attributes.rig`.

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

Retained video status `viewerConnected` remains informational only and does not participate in REDCON.

## Convergence Behavior

Rig receives target REDCON only through Sparkplug.

Current examples:

- target `redcon=4`
  - converge txing to the sleep state
  - reflect `sparkplug.state.reported.redcon=4`
  - clear the in-memory pending REDCON target on convergence
- target `redcon=3`
  - wake txing
  - once MCU is awake, reflect `sparkplug.state.reported.redcon=3`
  - if MCP/video conditions later satisfy higher derived levels, reported REDCON may rise naturally to `2` or `1`
  - clear the in-memory pending REDCON target once actual REDCON reaches the commanded REDCON

The current implementation keeps the current derived-behavior model rather than making REDCON a strict actuator state machine.

## Birth and Death Rules

### NBIRTH / NDEATH

Rig publishes Sparkplug node lifecycle as a proper `NBIRTH` / `NDEATH` pair:

- `NBIRTH` carries `bdSeq` and `rig.redcon=1`
- `NDEATH` carries the matching `bdSeq`
- the current implementation does not add node `NDATA`

### DBIRTH

Txing emits `DBIRTH` when the device is BLE-reachable.

Functional interpretation:

- if rig can see the device over BLE and can send wake commands, the txing device is born

### DDEATH

Txing emits `DDEATH` only for unexpected device loss on the same reachability timeout that currently drives `ble.online=false`:

- no matching advertisement observed for 30 seconds

Intentional GUI-off / `REDCON 4` sleep does not emit `DDEATH`. In that case the rig keeps the device in normal `sparkplug reported.redcon=4` lifecycle state and only reflects `mcu reported.online=false` once BLE presence ages out.

On unexpected-loss `DDEATH`, rig should best-effort:

- force `sparkplug.state.reported.redcon=4`
- clear any in-memory pending REDCON target

`DDEATH` wins over stale `reported.*` detail.

### Rebirth

When BLE reachability returns:

- emit a fresh `DBIRTH`
- restart convergence conservatively from observed state
- do not assume previous high REDCON state can be restored automatically

## Restart Behavior

Rig restart should be conservative:

- start from the current reported state only
- do not recover a persisted lifecycle target from shadow
- prefer stability over speed
- do not optimize for fast convergence

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

Actual REDCON still moves according to observed state:

- `3` after wakeup-state convergence
- `2` when retained MCP becomes available
- `1` when retained video readiness becomes available and fresh

## Boundaries

The current implementation includes:

- Sparkplug lifecycle command transport
- one writable Sparkplug metric: `redcon`
- Sparkplug lifecycle reporting for rig and txing
- shadow reflection of actual and transient desired lifecycle state
- continued use of current `mcu.*` and `board.*` operational detail

The current implementation does not include:

- additional writable Sparkplug lifecycle metrics beyond txing `redcon`
- town lifecycle management through Sparkplug
- direct shadow lifecycle control as an authoritative path
- user-facing REDCON selection in UI
- mobility or automatic handoff between rigs
- redefinition of lifecycle intent transport away from Sparkplug
