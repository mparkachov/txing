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
- The current UI stays simple: one on/off switch and one video button.
- UI lifecycle mapping is:
  - `on` -> request `redcon=3`
  - `off` -> request `redcon=4`
- Users do not directly select REDCON levels.
- `mcu.*` and `board.*` remain in shadow as supporting operational detail only.
- The current implementation keeps the viewer-dependent `REDCON 1` rule.

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
  -> reflects desired/report lifecycle state into txing AWS shadows only
  -> derives txing reported.redcon from current MCU + board operational detail

txing board control
  -> remains owner of reported.board.*

txing gateway / BLE path
  -> remains owner of reported.mcu.*
  -> determines BLE reachability for DBIRTH/DDEATH
```

## Authority and Ownership

- Sparkplug is the only authoritative lifecycle intent path.
- AWS shadow is reflection and durable restart cache only.
- `rig` is the only authority that computes top-level `txing.state.reported.redcon`.
- `board` remains the source of truth for `reported.board.*`.
- `rig` remains the source of truth for `reported.mcu.*`.
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

- `state.desired.redcon`
- `state.reported.redcon`
- `state.reported.batteryMv`
- supporting `reported.mcu.*`
- supporting `reported.board.*`

Semantics:

- `state.desired.redcon`
  - reflects the latest unresolved Sparkplug lifecycle intent
  - exists only as transient restart cache
  - is not an authoritative command ingress
  - is cleared when `reported.redcon` converges
  - is also cleared on unexpected-loss `DDEATH`
- `state.reported.redcon`
  - reflects the actual lifecycle state of txing
  - must match the Sparkplug device actual REDCON
- `state.reported.batteryMv`
  - reflects the actual lifecycle battery metric of txing
  - must match the Sparkplug device actual `batteryMv`
- Direct scalar attributes under `txing.state.reported` are the strict Sparkplug metric reflection surface.
  - In the current implementation lifecycle reflection metrics are `redcon` and `batteryMv`.
  - Phase 2 also adds Sparkplug device metrics under `services/mcp/*` as MCP discovery summary (availability, transport, descriptor topic, lease settings, and server/protocol versions).
  - `mcu.*` and `board.*` remain shadow-only operational detail and are not Sparkplug metric reflections.
- AWS IoT registry attributes hold stable per-device metadata outside the shadow:
  - `attributes.rig`
  - `attributes.bleDeviceId`

Example reflected txing shadow shape:

```json
{
  "state": {
    "desired": {
      "redcon": 3
    },
    "reported": {
      "redcon": 2,
      "batteryMv": 3972,
      "mcu": {
        "power": true
      },
      "board": {
        "power": true,
        "wifi": {
          "online": true
        },
        "video": {
          "ready": true,
          "viewerConnected": false
        }
      }
    }
  }
}
```

### Rig And Town Reflection

The current implementation does not maintain AWS IoT things or shadows for `rig` or `town`.

- `rig.redcon=1` exists only as a Sparkplug node metric in `NBIRTH`.
- `town` exists only as the Sparkplug group id.
- Rig membership comes from the dynamic AWS IoT thing group whose name matches `attributes.rig`.

## Current REDCON Semantics

The current implementation uses this txing REDCON ladder:

- `REDCON 4`
  - BLE reachable
  - MCU in the sleep state
- `REDCON 3`
  - MCU in the wakeup state
  - board not yet fully ready for the current video-derived readiness model
- `REDCON 2`
  - board powered
  - board Wi-Fi online
  - board video ready
  - no external viewer connected
- `REDCON 1`
  - same as `REDCON 2`
  - external viewer connected

The current implementation keeps `REDCON 1` dependent on `reported.board.video.viewerConnected`.

## Convergence Behavior

Rig receives target REDCON only through Sparkplug.

Current examples:

- target `redcon=4`
  - converge txing to the sleep state
  - reflect `state.reported.redcon=4`
  - clear `state.desired.redcon` on convergence
- target `redcon=3`
  - wake txing
  - once MCU is awake, reflect `state.reported.redcon=3`
  - if board/video conditions later satisfy higher derived levels, reported REDCON may rise naturally to `2` or `1`
  - clear `state.desired.redcon` once actual REDCON reaches the commanded REDCON

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

Intentional GUI-off / `REDCON 4` sleep does not emit `DDEATH`. In that case the rig keeps the device in normal `reported.redcon=4` lifecycle state and only reflects `reported.mcu.online=false` once BLE presence ages out.

On unexpected-loss `DDEATH`, rig should best-effort:

- force `state.reported.redcon=4`
- clear `state.desired.redcon`

`DDEATH` wins over stale `reported.board.*` detail.

### Rebirth

When BLE reachability returns:

- emit a fresh `DBIRTH`
- restart convergence conservatively from observed state
- do not assume previous high REDCON state can be restored automatically

## Restart Behavior

Rig restart should be conservative:

- check whether `state.desired.redcon` is still present
- if present, attempt convergence from current observed state
- prefer stability over speed
- do not optimize for fast convergence

A lingering `desired.redcon` after restart is treated as recoverable abnormal state, not normal steady-state behavior.

## UI Behavior

UI behavior stays intentionally simple:

- the user has one on/off switch
- the user has one video button
- the user does not select REDCON levels directly

Lifecycle mapping:

- UI `on` -> Sparkplug intent `redcon=3`
- UI `off` -> Sparkplug intent `redcon=4`

Actual REDCON still moves according to observed state:

- `3` after wakeup-state convergence
- `2` when board/video-ready conditions are satisfied
- `1` when an external viewer connects

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
- redefinition of `REDCON 1` to remove viewer dependency
