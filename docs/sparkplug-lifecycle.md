# Sparkplug Lifecycle

## Status

- Scope: current lifecycle control through Sparkplug with one writable metric: `redcon`
  and reflected availability metrics under `capability.*`
- Group model: `town` is the Sparkplug group id
- Edge model: `rig` is the Sparkplug edge node. A `raspi` edge node is the
  standalone `txing-sparkplug-manager` daemon; a `cloud` edge node is the
  AWS-hosted `txing-cloud-rig-lambda` runtime.
- Device model: each physical `txing` is one Sparkplug device and one AWS IoT thing
- Sparkplug MQTT is the source protocol
- The `sparkplug` named shadow is the AWS-side materialized Sparkplug view, not device intent storage
- `DCMD.redcon` is the only writable lifecycle command path

## Hard Edge Node Requirement

The rig is not a Sparkplug device. The rig is the Sparkplug edge node. In
production, `raspi` rigs publish that edge node from the standalone
`txing-sparkplug-manager` daemon, while `cloud` rigs publish it from
`txing-cloud-rig-lambda`.

- `spBv1.0/<town>/NBIRTH/<rig>` means the rig edge node is born.
- `spBv1.0/<town>/NDEATH/<rig>` means the rig edge node is dead.
- A born rig edge node is healthy REDCON 1. For `raspi`, if
  `rig-daemon.target` is running, both rig daemon services are active, and
  `just rig::check` passes, the rig thing's Sparkplug projection must be
  `NBIRTH` with `payload.metrics.redcon=1`. For `cloud`, the EventBridge minute
  schedule must refresh `NBIRTH` within the witness timeout. A retained
  `NDEATH`, missing `NBIRTH`, or any non-1 born rig REDCON in those conditions
  is a rig defect.
- This is a Sparkplug lifecycle contract, not a `rig::check` responsibility.
  `rig::check` remains a configuration and connectivity check; it is only one
  of the preconditions under which the Sparkplug projection is expected to show
  the born edge node state.
- `spBv1.0/<town>/DBIRTH/<rig>/...` and `spBv1.0/<town>/DDEATH/<rig>/...` must never represent the rig itself.
- `DBIRTH`, `DDATA`, and `DDEATH` are only for device things managed by the rig.
- Witness projects node `NBIRTH` and `NDEATH` messages onto the registered rig thing's `sparkplug` named shadow.
- systemd service status, Lambda invocation status, and AWS IoT MQTT lifecycle
  events are observability signals only; they do not replace Sparkplug `NBIRTH`
  and `NDEATH`.
- For `raspi`, the Sparkplug node MQTT session uses
  `<rig>-sparkplug-manager` as its AWS IoT MQTT client id. For `cloud`, the
  Lambda runtime publishes the same Sparkplug topic model from the AWS-hosted
  runtime. The Sparkplug edge node id in topics remains `<rig>`, but any
  transport client id must not collide with another rig/runtime client id.
- Managed device Sparkplug MQTT sessions use the managed thing name as their MQTT client id so AWS IoT thing connectivity tracks device session state.

## Authority and Ownership

- Sparkplug is the only authoritative lifecycle intent transport.
- AWS shadow is reflection and durable restart cache only.
- The rig runtime is the only authority that publishes Sparkplug node lifecycle
  for the rig edge node and device lifecycle for managed txing entities.
- Witness is the only authority that writes the AWS-side `sparkplug` named
  shadow projection for rig and managed device things.
- `board` remains the source of truth for board power, wifi, and video operational state.
- `rig` remains the source of truth for the `ble`, `power`, and `mcp` named
  shadows for BLE-managed devices.
- `cloud-mcu` runtime remains the source of truth for `sqs`, `power`, and
  future `ecs` named shadows for cloud-managed MCU devices.

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
- if an inventoried device has no current `sparkplug` availability when
  SparkplugManager starts, the manager publishes `DDEATH` once so stale projected
  `DBIRTH` or `DDATA` shadows from a previous process are cleared
- `sparkplug` is special: live `DBIRTH` and `DDATA` may report
  `capability.sparkplug=true`, while `DDEATH` remains the unavailable signal and
  still carries no device metrics

Capability-owned shadow rule:

- each capability that produces typed data owns its corresponding named shadow
- Sparkplug reflects only availability with `capability.<name>` and lifecycle
  with `redcon`
- a capability component that needs to update its shadow must publish named
  shadow MQTT topics such as
  `$aws/things/<thingName>/shadow/name/<capability>/update`; on standalone
  `raspi` rigs, `txing-ble-connectivity` sends those updates over local IPC and
  `txing-sparkplug-manager` forwards them to AWS IoT Core
- if a capability component needs to read its shadow, it must use the same AWS
  IoT named-shadow MQTT topic model with shadow `/get`, `/get/accepted`, and
  `/get/rejected` topics
- for BLE devices, `txing-ble-connectivity` owns the `ble` named shadow and
  device-domain shadows such as `power` and `weather`
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
- typed data such as `batteryMv` and weather readings must live
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
  - BLE is reachable; the rig keeps the BLE connection open when possible and the MCU advertises again after disconnect
  - unit stack power/D1 is disabled
- `REDCON 3`
  - BLE is reachable
  - unit stack power/D1 is enabled
  - MCP is not yet available
- `REDCON 2`
  - BLE is reachable
  - unit stack power/D1 is enabled
  - MCP is available
  - retained video status is not yet ready
- `REDCON 1`
  - BLE is reachable
  - unit stack power/D1 is enabled
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
directly, but orders them against BLE REDCON evidence. In this contract `power`
means MCU-controlled wakeup power/D1 availability, not MCU power. When newer BLE
state reports REDCON `4` or otherwise reports `power=false`, SparkplugManager
clears `board`, `mcp`, and `video` immediately instead of waiting for the
retained board state to expire. A later board daemon capability state with a
newer observation timestamp can raise board-owned capabilities again; older
board retained state cannot override newer BLE REDCON 4 evidence.
BLE state-read and command-applied capability states carry internal
`metrics.bleRedcon` evidence for this gate; advertisement-only BLE reachability
does not.
Together with BLE `sparkplug`/`ble`/`power` state, upgraded unit devices can
converge through the full REDCON ladder.

Commandable REDCON levels are a txing type capability, exposed as the comma-separated
`redconCommandLevels` thing attribute from each device manifest's `redcon_command_levels`.
The UI still displays the current Sparkplug REDCON even when that level is not commandable,
but it only enables switching to levels listed for the thing type.

## Convergence Behavior

Rig receives target REDCON only through Sparkplug.

- target `redcon=4`
  - converge txing to the sleep state
  - publish Sparkplug device `redcon=4`
  - keep BLE connected when possible for idle state and measurement updates
  - clear the in-memory pending REDCON target on convergence
- target `redcon=3`
  - wake txing
  - once unit stack power/D1 is enabled, publish Sparkplug device `redcon=3`
  - if MCP/video conditions later satisfy higher derived levels, actual REDCON may rise naturally to `2` or `1`
  - clear the in-memory pending REDCON target once actual REDCON reaches the commanded REDCON

The current implementation keeps the derived-behavior model rather than making REDCON a strict actuator state machine.

## Deploy Boundary

- `shared/aws` owns the nested AWS stacks.
- `just aws::deploy` deploys the base stack, including the Sparkplug witness Lambda infrastructure, IoT rule, and role.
- `just aws::publish-lambda` deploys release-built witness Lambda code.
- `witness/` owns the Lambda source and tests, not a separate primary stack.
