# Sparkplug Lifecycle

## Status

- Scope: current lifecycle control through Sparkplug with one writable metric: `redcon`
- Group model: `town` is the Sparkplug group id
- Edge model: `rig` is the Sparkplug edge node
- Device model: each physical `txing` is one Sparkplug device and one AWS IoT thing
- Sparkplug MQTT is the source protocol
- The `sparkplug` named shadow is the AWS-side materialized Sparkplug view, not device intent storage
- `DCMD.redcon` is the only writable lifecycle command path

## Authority and Ownership

- Sparkplug is the only authoritative lifecycle intent transport.
- AWS shadow is reflection and durable restart cache only.
- `rig` is the only authority that publishes Sparkplug lifecycle state for rig and txing entities.
- Witness is the only authority that writes the AWS-side `sparkplug` named shadow projection for rig and unit things.
- `board` remains the source of truth for board power, wifi, and video operational state.
- `rig` remains the source of truth for `mcu` and `mcp` named shadows.

## Topic Model

Witness accepts only these topic shapes:

- `spBv1.0/<groupId>/<messageType>/<edgeNodeId>`
- `spBv1.0/<groupId>/<messageType>/<edgeNodeId>/<deviceId>`

Supported message types:

- Node: `NBIRTH`, `NDATA`, `NDEATH`
- Device: `DBIRTH`, `DDATA`, `DDEATH`

Topic identity is not inferred from Sparkplug metrics. It comes only from the MQTT topic.

## Shadow Projection Model

Witness materializes Sparkplug into `namedShadows.sparkplug.state.reported` with:

- `topic`
  - `namespace`
  - `groupId`
  - `messageType`
  - `edgeNodeId`
  - optional `deviceId`
- `payload`
  - optional `timestamp`
  - optional `seq`
  - `metrics`
- `projection`
  - `observedAt`

Example projected txing shadow:

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
          "redcon": 2,
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

Metric path rules:

- split both `.` and `/` into nested object path segments
- `redcon` -> `payload.metrics.redcon`
- `batteryMv` -> `payload.metrics.batteryMv`

Projection behavior:

- `NBIRTH` and `DBIRTH`
  - replace `payload.metrics`
- `NDATA` and `DDATA`
  - deep-merge changed metrics into existing `payload.metrics`
  - preserve omitted metrics
- `NDEATH` and `DDEATH`
  - replace `payload.metrics` with the actual death payload
  - preserve topic/message metadata and update `projection.observedAt`

Current rig death payload policy:

- `NDEATH` carries `bdSeq` and `redcon=4`
- `DDEATH` carries `redcon=4` and the last `batteryMv`

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

## Deploy Boundary

- `shared/aws` owns the shared town stack resources.
- `witness/` owns the Sparkplug witness Lambda, IoT rule, role, and log group.
- `just witness::deploy` packages and deploys the witness stack independently.
