# Sparkplug Lifecycle

## Status

- Scope: current lifecycle control through Sparkplug with one writable metric: `redcon`
- Group model: `town` is the Sparkplug group id
- Edge model: `rig` is the Sparkplug edge node and Greengrass Lite core
- Device model: each physical `txing` is one Sparkplug device and one AWS IoT thing
- Sparkplug MQTT is the source protocol
- The `sparkplug` named shadow is the AWS-side materialized Sparkplug view, not device intent storage
- `DCMD.redcon` is the only writable lifecycle command path

## Hard Edge Node Requirement

The rig is not a Sparkplug device. The rig is the Sparkplug edge node, and in
production that edge node is the Greengrass Lite core running
the unit device Sparkplug process component.

- `spBv1.0/<town>/NBIRTH/<rig>` means the Greengrass Lite rig edge node is born.
- `spBv1.0/<town>/NDEATH/<rig>` means the Greengrass Lite rig edge node is dead.
- `spBv1.0/<town>/DBIRTH/<rig>/...` and `spBv1.0/<town>/DDEATH/<rig>/...` must never represent the rig itself.
- `DBIRTH`, `DDATA`, and `DDEATH` are only for txing/unit things managed by the rig.
- Witness projects node `NBIRTH` and `NDEATH` messages onto the registered rig thing's `sparkplug` named shadow.
- Greengrass core/device/component status and AWS IoT MQTT lifecycle events are observability signals only; they do not replace Sparkplug `NBIRTH` and `NDEATH`.

## Authority and Ownership

- Sparkplug is the only authoritative lifecycle intent transport.
- AWS shadow is reflection and durable restart cache only.
- `rig` is the only authority that publishes Sparkplug node lifecycle for the rig edge node and device lifecycle for managed txing entities.
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
For the rig thing, witness resolves node topics by matching
`edgeNodeId=<rig>` and `groupId=<town>` to the registered rig thing. For managed
txing/unit things, witness uses the device id segment in the device topic.

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
- `DDEATH` carries no device metrics; `payload.metrics` is an empty object in the witness projection

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

The root [README](../README.md) is the canonical lifecycle contract. In brief:

- `DDEATH` means the device is unavailable and `redcon` is not defined.
- `DBIRTH` / `DDATA` with `redcon=4` means the device is alive but in the sleep state.

The born-state REDCON ladder is:

- `REDCON 4`
  - MCU is in the sleep state
  - BLE presence is still online through the rendezvous advertisements
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

- `shared/aws` owns the nested AWS stacks.
- `just aws::deploy` deploys the base stack, including the Sparkplug witness Lambda, IoT rule, and role.
- `witness/` owns the Lambda source and tests, not a separate primary deployment flow.
