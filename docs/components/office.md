# Office

The office app is the operator and admin SPA for browsing towns, rigs, and devices, reading the current projected state, opening board video, and sending lifecycle and MCP actions.

## Current Scope

- static SPA built with Vite
- Cognito hosted UI sign-in
- configured Cognito User Pool membership as the office access boundary
- Cognito Identity Pool exchange for temporary AWS credentials
- direct AWS IoT reads for initial route metadata
- MQTT 5 over WebSocket for live named-shadow updates, Sparkplug commands and
  MQTT MCP traffic. [AWS IoT MQTT policy](../aws.md#iot-mqtt)
- AWS KVS WebRTC viewer for the `/<town>/<rig>/<device>/video` route

## Access Model

Office users are enrolled in the configured Cognito User Pool. Operators add
users in the AWS Cognito console, and users sign in through the existing Cognito
Hosted UI flow. All enrolled users share the same current office permissions
through the authenticated Cognito Identity Pool role; office does not use
Cognito groups, custom claims, per-device restrictions, or an in-app user
management screen.

## Routes

- `/<townThingName>`
- `/<townThingName>/<rigThingName>`
- `/<townThingName>/<rigThingName>/<deviceThingName>`
- `/<townThingName>/<rigThingName>/<deviceThingName>/video`

The video route is derived from the selected route and office origin. It is not stored in Thing Shadow or board config.

## Current Transport Split

- route breadcrumbs and first-load metadata: AWS IoT HTTPS APIs
- live shadow updates: named Thing Shadow over MQTT/WSS
- lifecycle commands: Sparkplug `DCMD.redcon` for devices and `NCMD.redcon` for
  rigs over MQTT/WSS
- Unit control at REDCON `1`: MCP over the `txing.mcp.v1` WebRTC data channel
  on the board video KVS session
- Unit control at REDCON `2`: MCP over MQTT/WSS when the daemon advertises
  MQTT-only MCP because video is unavailable/not ready
- TBot and Cyberbrick control at REDCON `1` and `2`: a separate MAVLink data
  peer with View only and explicit Control. [Board MAVLink contract](../contracts/board-mavlink.md#office-operation-and-safety-semantics)
- Virtual quadcopter flight during an operational session: separate camera
  and MAVLink peers, with an explicit flight lease gated by decoded video
  and fresh telemetry. [Virtual quadcopter flight](../../devices/virtual-quad/README.md#flight-in-office)
- active control requires an explicit take-control action
- board video: AWS KVS WebRTC

The app expects `capabilities` to include `sparkplug` and uses it to decide which named shadows should exist for a selected thing.
For both rig and device routes, Sparkplug `NDEATH`/`DDEATH` means unavailable:
REDCON indicators are grayed and REDCON command controls are disabled until the
thing is born again. Rig routes read `redconCommandLevels=1,4` from thing
metadata and publish to `spBv1.0/<town>/NCMD/<rig>`.

For `unit` devices, the Go unit daemon publishes retained
`txings/<device_id>/capability/v2/state` messages for `board`, `mcp`, and
`video`. Sparkplug projection reflects those into the capability stack; `video`
becomes enabled only when the native KVS worker is ready.

The office app must not derive board/MCP/video availability locally from pending
commands or client-side transport state. Capability indicators reflect the
Sparkplug named shadow projection. A small delay is acceptable; inconsistent
client-side capability prediction is not.

The device registry selects a type-owned web adapter. The virtual-quad session
adapter interprets the matching simulation and Sparkplug projections, supplies
REDCON command state to the shared selector and renders its camera and flight
panel. Office provides the authenticated shadow reader, command publishing,
navigation, capability stack and notification stream. The detail-route MAVLink
indicator reflects heartbeat reception by its browser peer. Media connection
state has no authority to advance the reported REDCON.
[Virtual quadcopter architecture](../virtual-quadcopter-architecture.md#office-and-flight-authority)

## Debug

Open **Debug** from the profile menu on a device page. Office shows one
read-only JSON panel per named shadow declared by the device. **Load Shadow**
refreshes the MQTT snapshots. The Agent panel refreshes over HTTPS and shows
its own read status. Device-specific diagnostics appear above the panels.

## Local Development

Install and write the local env:

```bash
just office::install
just office::write-env
just office::dev
```

Manual fallback:

```bash
cp office/.env.example office/.env.local
```

`office::write-env` writes:

- `VITE_AWS_REGION`
- `VITE_TOWN_THING_NAME`
- `VITE_SPARKPLUG_GROUP_ID`
- Cognito and IoT values from `/txing/stack/...` SSM parameters

The office bundle version is injected by Vite from `office/package.json` during
the build. The package version is kept aligned with `release/versions/office`,
and the version is not a Cloudflare environment variable.

Local Cognito sign-in remains allowed for:

- `http://localhost:5173/`
- `http://127.0.0.1:5173/`

## Cloudflare Pages

```bash
just office::build
```

Production office publishing is handled by Cloudflare Pages from Git, not by a
txing deploy action, AWS S3, or CloudFront upload. Use these Cloudflare Pages
settings:

- Project: `txing-office`
- Root directory: `office`
- Build command: `bun install --frozen-lockfile && bun --bun run build`
- Deploy command: leave empty; Cloudflare Pages publishes `dist`
- Build output directory: `dist`
- Domain: `office.txing.dev`
- Environment variables:
  - `BUN_VERSION=1.3.11`
  - `VITE_AWS_REGION`
  - `VITE_TOWN_THING_NAME`
  - `VITE_SPARKPLUG_GROUP_ID`
  - `VITE_COGNITO_DOMAIN`
  - `VITE_COGNITO_CLIENT_ID`
  - `VITE_COGNITO_USER_POOL_ID`
  - `VITE_COGNITO_IDENTITY_POOL_ID`
  - `VITE_IOT_POLICY_NAME`
  - `VITE_COGNITO_SCOPE`

Cloudflare Pages provides SPA fallback automatically when there is no top-level
`404.html`. The app does not use a `/* /index.html 200` `_redirects` rule
because Pages now treats that as an infinite loop. `just office::deploy` is a
legacy informational recipe that prints the Cloudflare Pages settings; it does
not deploy AWS infrastructure or publish artifacts.

## Public Sign-In Entry

The public `txing.dev` site is a separate Cloudflare Pages project under
`www/`. Its sign-in link points to `https://office.txing.dev/?signin=1`.
The office SPA consumes that query parameter, starts the existing PKCE Cognito
flow from the office origin, and Cognito returns to `https://office.txing.dev/`.
`txing.dev` is not a Cognito callback URL for this entry flow.
Production sign-off redirects through Cognito to `https://txing.dev/`; local
development sign-off returns to the current local office origin.

AWS bootstrap, admin-user creation, and teardown live in [aws.md](../aws.md).
