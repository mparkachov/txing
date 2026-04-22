# Phase 2: Txing MCP Over MQTT

## Status

- Phase: 2 design
- Scope: board-hosted MCP server exposed over MQTT
- First MCP capability: `cmd_vel`
- Web integration target: the SPA uses MCP over its existing AWS IoT MQTT/WSS session
- Thing Shadow role: not used for MCP discovery or MCP runtime state
- Sparkplug publication model: `board` publishes retained MQTT state and `rig` mirrors selected MCP facts into the Sparkplug device session

## Purpose

This document defines the Phase 2 design for exposing a board-hosted MCP server as the remote API surface for txing. The first tool is `cmd_vel`, but the design is intended to be reusable for additional board-side tools later.

The design has three goals:

- provide a stable remote API over MCP instead of treating `cmd_vel` as a raw ad hoc MQTT topic
- make the MCP server discoverable to the web app and other future clients
- surface service availability through Sparkplug without extending the Thing Shadow for MCP
- use retained MQTT state as the board-to-rig status path instead of relying on shadow for MCP availability

## Current Context

Today, the relevant runtime split is:

- `board` owns `board.*` in the shared device Thing Shadow
- `rig` owns the current Sparkplug lifecycle publication model
- `web` already maintains an authenticated AWS IoT MQTT/WSS session
- `web` is now route-driven at `/<town>/<rig>/<device>` and `/<town>/<rig>/<device>/video`
- the active rig and device are selected at runtime from the current route
- `device` is the AWS IoT thing name and stable `device_id`
- Phase 3 removes the legacy direct MQTT `<device-id>/board/cmd_vel` path; MCP is now the only remote board control API.

The current lifecycle design treats Sparkplug as authoritative for lifecycle management. The current implemented Sparkplug structure is:

- group: `<town>`
- node: `<rig>`
- device: `<device-id>`

That structure is preserved in this design unless an explicit future decision changes it.

## Route, Identity, and Derived URL Model

This phase-2 design follows the route-driven model delivered under epic `txing-5jn`.

The identity model is:

- `town` is the deployment-scoped Sparkplug group id
- `rig` is the route-selected AWS IoT dynamic thing-group name and Sparkplug edge node id
- `device` is the route-selected AWS IoT thing name and stable `device_id`

The canonical browser routes are:

- `/<town>/<rig>/<device>`
- `/<town>/<rig>/<device>/video`

Video delivery is now derived, not stored as a canonical URL fact:

- the browser video route is computed from the current web origin and the selected route
- the KVS signaling channel is derived from the device id as `<device-id>-board-video`
- board-published metadata should describe service or session facts, not override the canonical browser route

The MCP design follows the same rule. It should publish stable transport identifiers and topic roots, not full browser URLs that are already derived from the route schema.

## Design Summary

Phase 2 introduces a board-hosted MCP server named `mcp`.

The board exposes that server over a custom MQTT transport that preserves MCP JSON-RPC message format and MCP lifecycle rules. The web app uses the existing AWS IoT MQTT/WSS connection to act as an MCP client.

Discovery is split into two layers:

- retained MQTT board-published topics provide the detailed connection and transport metadata required to open an MCP session
- `rig` mirrors selected MCP discovery and availability facts into Sparkplug for the selected device

The Thing Shadow is intentionally not used for MCP discovery or MCP runtime state.

In the short and medium term, this is also the migration path away from shadow as the board-to-rig status mechanism for MCP-related state:

- `board` publishes retained MQTT state directly
- `rig` subscribes to that retained MQTT state
- `rig` reflects the selected device status into Sparkplug

## Goals

- Expose a board-hosted MCP server over MQTT.
- Make `cmd_vel` available as an MCP tool.
- Allow the web app to discover and use the MCP server over the already established MQTT connection.
- Publish enough service metadata for discovery through Sparkplug.
- Keep the design broad enough to support additional future board-side MCP tools.

## Non-Goals

- Implementing the server in this phase document
- Expanding the Thing Shadow schema for MCP
- Defining non-board MCP services in detail
- Resolving all future Sparkplug multi-service ownership questions in this phase

## Naming

The MCP server is named `mcp`.

This name is used consistently in:

- Sparkplug metric names
- retained MQTT descriptor topics
- MQTT session topic roots
- client-visible service identity

MQTT path examples in this document use `<device-id>` because the active device is now selected dynamically from the current route rather than being a single fixed thing name.

## MQTT Topic Naming Convention

The chosen naming convention is device-first.

The topic root is:

```text
txings/<device-id>/mcp
```

Initial topic set:

```text
txings/<device-id>/mcp/descriptor
txings/<device-id>/mcp/status
txings/<device-id>/mcp/session/{sessionId}/c2s
txings/<device-id>/mcp/session/{sessionId}/s2c
```

Rationale:

- it keys the transport by stable device identity rather than a single hardcoded thing name
- it matches the new town/rig/device drilldown model where device selection is dynamic
- it avoids baking town and rig into the MQTT transport root because those are current-assignment context, not the stable device identifier
- it treats MCP as the single per-device remote API endpoint instead of nesting an extra service name under `mcp`
- the plural `txings/` namespace makes the collection root explicit before the per-device segment begins

This convention applies to the MCP topic family introduced by Phase 2 and carried forward by Phase 3. The legacy non-MCP raw `cmd_vel` topic was removed in Phase 3.

## Discoverability

The chosen discovery model is Sparkplug summary plus retained MQTT descriptor.

### Sparkplug discovery summary

Sparkplug is the high-level discovery surface. It tells clients that `mcp` exists for the selected device and whether it is available.

`rig` is the only publisher of the selected `<town>/<rig>/<device-id>` Sparkplug device session. It mirrors MCP discovery and availability from board-published retained MQTT state into the Sparkplug metrics for that device.

Intended metric family under the selected Sparkplug device `<device-id>`:

- `services/mcp/available`
- `services/mcp/transport`
- `services/mcp/mcpProtocolVersion`
- `services/mcp/descriptorTopic`
- `services/mcp/leaseRequired`
- `services/mcp/leaseTtlMs`
- `services/mcp/serverVersion`

The Sparkplug summary is intentionally compact. It should be enough to let a client detect service presence and find the retained descriptor topic.

### Retained MQTT descriptor

Detailed transport metadata is published on a retained MQTT topic:

```text
txings/<device-id>/mcp/descriptor
```

The retained descriptor is the detailed source of truth for connection metadata. It contains the information a client needs to establish an MCP session over MQTT.

The board is the source of truth for the retained MCP topics:

- `txings/<device-id>/mcp/descriptor`
- `txings/<device-id>/mcp/status`

Expected descriptor fields:

- `serviceId`
- `serverInfo`
- `transport`
- `mcpProtocolVersion`
- `topicRoot`
- `sessionTopicPattern`
- `leaseRequired`
- `leaseTtlMs`
- `serverVersion`

The descriptor must not publish canonical browser routes such as the video page URL. Those are derived from the active route schema and web origin, not treated as server-owned facts.

Illustrative descriptor shape:

```json
{
  "serviceId": "mcp",
  "serverInfo": {
    "name": "mcp",
    "version": "0.1.0"
  },
  "transport": "mqtt-jsonrpc",
  "mcpProtocolVersion": "2025-11-25",
  "topicRoot": "txings/<device-id>/mcp",
  "sessionTopicPattern": {
    "clientToServer": "txings/<device-id>/mcp/session/{sessionId}/c2s",
    "serverToClient": "txings/<device-id>/mcp/session/{sessionId}/s2c"
  },
  "leaseRequired": true,
  "leaseTtlMs": 5000,
  "serverVersion": "0.1.0"
}
```

### Client discovery flow

The expected discovery flow is:

1. `board` publishes retained MCP descriptor and status topics for `<device-id>`.
2. `rig` subscribes to that retained MQTT state and mirrors selected facts into Sparkplug `services/mcp/*`.
3. Client observes Sparkplug metrics for `services/mcp/*`.
4. Client checks `services/mcp/available`.
5. Client reads the retained descriptor topic referenced by Sparkplug.
6. Client opens an MCP session over MQTT using the descriptor metadata.
7. Client performs MCP initialization and begins tool use.

## MCP Transport

The transport is a custom MQTT transport for MCP.

The transport must preserve all MCP protocol expectations that are independent of HTTP or stdio:

- JSON-RPC 2.0 message format
- UTF-8 encoded messages
- MCP initialization lifecycle
- negotiated capability boundaries
- explicit session teardown through underlying transport closure

The board-hosted server is tools-only in v1. Resources, prompts, and other MCP features are deferred.

### Session Topics

Each client session uses a dedicated pair of topics:

- client to server: `txings/<device-id>/mcp/session/{sessionId}/c2s`
- server to client: `txings/<device-id>/mcp/session/{sessionId}/s2c`

This keeps request and response traffic isolated per client session and avoids cross-client ambiguity.

### MCP Lifecycle

The MQTT transport must preserve normal MCP lifecycle order:

1. client sends `initialize`
2. server responds with capabilities and server info
3. client sends `notifications/initialized`
4. normal MCP operation begins

The design does not introduce any MQTT-specific shortcut that bypasses MCP initialization.

## Initial MCP Tool Surface

The first tool surface is intentionally small.

Initial tools:

- `control.acquire_lease`
- `control.renew_lease`
- `control.release_lease`
- `cmd_vel.publish`
- `cmd_vel.stop`

### `cmd_vel.publish`

`cmd_vel.publish` is the first motion tool. It preserves the current semantic contract of `cmd_vel`.

Semantics:

- `linear.x` is forward body velocity in `m/s`
- `angular.z` is yaw rate in `rad/s`
- `linear.y`, `linear.z`, `angular.x`, and `angular.y` remain unsupported and must be `0`

The MCP layer changes the API surface, not the motion meaning.

## Control Lease Model

A lease is required for motion control.

This is a design decision, not an open point.

Requirements:

- a client must acquire a lease before calling `cmd_vel.publish`
- a lease is short-lived and must be renewed while active
- lease expiry must stop motion immediately
- disconnect must stop motion immediately
- explicit release must stop motion
- a client without a valid lease cannot control motion

Rationale:

- it prevents mixed operators
- it gives a clear ownership model for teleop
- it creates a controlled path for future non-web clients

Illustrative lease flow:

1. client discovers the service
2. client initializes MCP
3. client calls `control.acquire_lease`
4. client calls `cmd_vel.publish` while renewing the lease
5. client calls `cmd_vel.stop`
6. client calls `control.release_lease`

## Board Responsibilities

In this design, `board` is responsible for:

- hosting the `mcp` server
- exposing the MCP session topics
- publishing the retained MQTT descriptor
- publishing retained current service status on MQTT
- enforcing lease ownership
- mapping `cmd_vel.publish` to the existing board motion pipeline
- stopping motion on lease loss, disconnect, or explicit stop

The board-hosted MCP server is the intended authoritative remote API surface for board motion control.

For discovery and status publication, `board` is also responsible for:

- publishing retained MCP facts under `txings/<device-id>/mcp/...`
- publishing enough state for `rig` to mirror MCP availability into Sparkplug
- using MQTT connection semantics, including retained state and offline behavior, as the board-to-rig status path for MCP

## Web Responsibilities

In this design, `web` is responsible for:

- reusing the existing AWS IoT MQTT/WSS connection
- acting as an MCP client over MQTT
- discovering `mcp`
- fetching the retained descriptor
- opening and initializing an MCP session
- acquiring and renewing the motion lease during teleop
- releasing the lease and stopping motion on exit

Phase 3 removes raw MQTT publish to `<device-id>/board/cmd_vel`; the web app now uses MCP only.

The web app also continues to treat browser URLs as derived route values:

- the canonical detail route is `/<town>/<rig>/<device>`
- the canonical video route is `/<town>/<rig>/<device>/video`
- MCP descriptor data must not attempt to replace or redefine those routes

## Rig Responsibilities

In this design, `rig` is responsible for:

- remaining the only publisher of the selected `<town>/<rig>/<device-id>` Sparkplug device session
- subscribing to board-published retained MQTT state for MCP
- mirroring selected `mcp` discovery and availability facts into Sparkplug `services/mcp/*`
- keeping lifecycle authority and lifecycle command handling unchanged

This keeps Sparkplug session ownership coherent while removing shadow from the MCP status path.

## Thing Shadow Position

The Thing Shadow is not used for MCP discovery or MCP runtime state.

That means:

- no new `board.mcp.*` discovery structure is introduced in the shadow for this phase
- no MCP availability summary is placed in `reported.device.board.*` for discovery purposes
- shadow remains focused on board operational state, not MCP service discovery

This keeps MCP discovery separate from the existing shadow ownership and lifecycle reflection model.

## Sparkplug Publication Model

The Sparkplug publication model is resolved for Phase 2.

Chosen model:

- `board` publishes retained MQTT state for MCP under `txings/<device-id>/mcp/...`
- `rig` subscribes to that retained MQTT state
- `rig` remains the only publisher of the selected `<town>/<rig>/<device-id>` Sparkplug device session
- `rig` mirrors selected MCP discovery and availability facts into Sparkplug `services/mcp/*`

This model is chosen because:

- it removes shadow from the MCP status path
- it avoids split `DBIRTH` / `DDATA` / sequence ownership across `rig` and `board`
- it preserves `rig` lifecycle authority
- it allows board availability to be expressed immediately through retained MQTT state and offline MQTT behavior

Phase-2 intent:

- short and medium term, use retained MQTT as the board-to-rig status path for MCP and mirror it into Sparkplug
- long term, continue reducing reliance on shadow for device status so Sparkplug becomes the primary external device-status surface

That means the design is stable on:

- device-first MQTT topics
- Sparkplug summary plus retained MQTT descriptor discovery
- board-hosted MCP server
- web as MCP client over existing MQTT/WSS
- lease-based motion control

## Implementation Alignment

Current Phase-2 implementation aligns with this model:

- `board` publishes retained descriptor and status on `txings/<device-id>/mcp/{descriptor,status}` and serves session JSON-RPC traffic on `txings/<device-id>/mcp/session/{sessionId}/{c2s,s2c}`.
- `board` enforces lease ownership for `cmd_vel.publish`/`cmd_vel.stop`, stops motion on lease release/expiry, and publishes retained unavailable status on disconnect using MQTT will semantics.
- `rig` subscribes to retained MCP descriptor/status topics and mirrors `services/mcp/*` Sparkplug metrics in its device `DBIRTH`/`DDATA` payloads while remaining the only Sparkplug publisher for that device session.
- `web` consumes Sparkplug `services/mcp/*` discovery summary, reads retained MCP descriptor/status topics, and uses MCP tool calls for teleop lease and `cmd_vel` control on the route-selected device.

## Acceptance Criteria For Phase 2 Design

This phase-2 design is complete when:

- the MQTT topic naming convention is documented
- the discovery model is documented
- the route-driven device identity and derived video URL model are documented
- the MCP transport and lifecycle expectations are documented
- the initial tool surface is documented
- the lease model is documented
- the Thing Shadow exclusion is documented
- the retained MQTT -> rig mirror -> Sparkplug publication model is documented
- `rig` is explicitly documented as the only publisher of the selected Sparkplug device session

## Next Step

The next step after this document is implementation planning and delivery against the resolved publication model, not further architecture debate about Sparkplug co-publish for Phase 2.
