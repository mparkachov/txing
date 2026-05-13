# Sparkplug Lifecycle

## Status

- Scope: current lifecycle control through Sparkplug with one writable metric: `redcon`
  and reflected availability metrics under `capability.*`
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
- The Sparkplug node MQTT session uses `<rig>-sparkplug-manager` as its AWS IoT MQTT client id. The Sparkplug edge node id in topics remains `<rig>`, but the transport client id must not collide with the Greengrass core MQTT client id.
- Managed device Sparkplug MQTT sessions use the managed thing name as their MQTT client id so AWS IoT thing connectivity tracks device session state.

## Authority and Ownership

- Sparkplug is the only authoritative lifecycle intent transport.
- AWS shadow is reflection and durable restart cache only.
- `rig` is the only authority that publishes Sparkplug node lifecycle for the rig edge node and device lifecycle for managed txing entities.
- Witness is the only authority that writes the AWS-side `sparkplug` named shadow projection for rig and unit things.
- `board` remains the source of truth for board power, wifi, and video operational state.
- `rig` remains the source of truth for the `ble`, `power`, and `mcp` named shadows for BLE-managed devices.

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
          "capability": {
            "sparkplug": true,
            "ble": true,
            "power": false
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

Metric path rules:

- split both `.` and `/` into nested object path segments
- `redcon` -> `payload.metrics.redcon`
- `capability.ble` -> `payload.metrics.capability.ble`

Capability availability rules:

- each managed device thing has a comma-separated `capabilities` thing attribute
  derived from its device type definition
- SparkplugManager reflects every capability from that attribute as a boolean
  Sparkplug metric named `capability.<name>`
- `true` means the corresponding named shadow or data domain is active and
  current enough for logic to use
- `false` means the corresponding named shadow or data domain is stale and must
  not be used in logic, even if older data metrics are still present from a
  previous `DDATA` merge
- on startup and inventory refresh, SparkplugManager initializes declared
  non-`sparkplug` capabilities to `false`; fresh connectivity adapter state can
  raise them to `true`
- `sparkplug` is special: live `DBIRTH` and `DDATA` may report
  `capability.sparkplug=true`, while `DDEATH` remains the unavailable signal and
  still carries no device metrics

Capability-owned shadow rule:

- each capability that produces typed data owns its corresponding named shadow
- Sparkplug reflects only availability with `capability.<name>` and lifecycle
  with `redcon`
- a capability component that needs to update its shadow must do so itself
  through Greengrass IPC to AWS IoT Core, using named shadow MQTT topics such as
  `$aws/things/<thingName>/shadow/name/<capability>/update`
- if a capability component needs to read its shadow, it must use the same
  Greengrass IoT Core IPC path with shadow `/get`, `/get/accepted`, and
  `/get/rejected` topics
- for BLE devices, `dev.txing.rig.BleConnectivity` owns the `ble` named shadow
  and device-domain shadows such as `power` and `weather`
- capability-owned named shadows must contain only required domain fields; they
  must not publish generic bookkeeping fields such as `observedAtMs` or `seq`
- readers that need freshness or ordering for a named shadow should use AWS IoT
  Shadow metadata timestamps and the root shadow `version`

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

Current device metric policy:

- device `DBIRTH` and `DDATA` carry `redcon` and the complete
  `capability.*` boolean availability surface for the device type
- availability and lifecycle helper metrics such as `bleConnected`,
  `mcpAvailable`, and `mode` are deprecated and must not be published as
  Sparkplug metrics; use `capability.*` and `redcon` instead
- typed data such as `batteryMv`, weather readings, and time readings must live
  in the corresponding capability-owned named shadows
- command-result metrics such as `redconCommandStatus` still use Sparkplug for
  the current command feedback path; `redconCommandSeq` is the command
  correlation field

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
  - device is in the sleep state
  - BLE presence is still online through rendezvous advertisements
- `REDCON 3`
  - BLE is reachable
  - unit stack power is enabled
  - MCP is not yet available
- `REDCON 2`
  - BLE is reachable
  - unit stack power is enabled
  - MCP is available
  - retained video status is not yet ready
- `REDCON 1`
  - BLE is reachable
  - unit stack power is enabled
  - MCP is available
  - retained video status is ready and fresh

For the upgraded `unit` rollout, all REDCON levels are declared in the type catalog
so later board/MCP/video v2 capability publication does not require AWS catalog
changes:

- `4 = ["sparkplug", "ble"]`
- `3 = ["sparkplug", "ble", "power"]`
- `2 = ["sparkplug", "ble", "power", "board", "mcp"]`
- `1 = ["sparkplug", "ble", "power", "board", "mcp", "video"]`

The board runtime publishes retained v2 capability state for `board`, `mcp`, and
`video`. SparkplugManager consumes those board-owned retained state messages
directly. Together with BLE `sparkplug`/`ble`/`power` state, upgraded unit
devices can converge through the full REDCON ladder.

Commandable REDCON levels are a txing type capability, exposed as the comma-separated
`redconCommandLevels` thing attribute from each device manifest's `redcon_command_levels`.
The UI still displays the current Sparkplug REDCON even when that level is not commandable,
but it only enables switching to levels listed for the thing type.

## Convergence Behavior

Rig receives target REDCON only through Sparkplug.

- target `redcon=4`
  - converge txing to the sleep state
  - publish Sparkplug device `redcon=4`
  - clear the in-memory pending REDCON target on convergence
- target `redcon=3`
  - wake txing
  - once unit stack power is enabled, publish Sparkplug device `redcon=3`
  - if MCP/video conditions later satisfy higher derived levels, actual REDCON may rise naturally to `2` or `1`
  - clear the in-memory pending REDCON target once actual REDCON reaches the commanded REDCON

The current implementation keeps the derived-behavior model rather than making REDCON a strict actuator state machine.

## Deploy Boundary

- `shared/aws` owns the nested AWS stacks.
- `just aws::deploy` deploys the base stack, including the Sparkplug witness Lambda, IoT rule, and role.
- `witness/` owns the Lambda source and tests, not a separate primary deployment flow.
