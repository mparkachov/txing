# Office

The office app is the operator and admin SPA for browsing towns, rigs, and devices, reading the current projected state, opening board video, and sending lifecycle and MCP actions.

## Current Scope

- static SPA built with Vite
- Cognito hosted UI sign-in
- Cognito Identity Pool exchange for temporary AWS credentials
- direct AWS IoT reads for initial route metadata
- MQTT/WSS for live named-shadow updates, Sparkplug commands, and MCP traffic
- AWS KVS WebRTC viewer for the `/<town>/<rig>/<device>/video` route

## Routes

- `/<townThingName>`
- `/<townThingName>/<rigThingName>`
- `/<townThingName>/<rigThingName>/<deviceThingName>`
- `/<townThingName>/<rigThingName>/<deviceThingName>/video`

The video route is derived from the selected route and office origin. It is not stored in Thing Shadow or board config.

## Current Transport Split

- route breadcrumbs and first-load metadata: AWS IoT HTTPS APIs
- live shadow updates: named Thing Shadow over MQTT/WSS
- lifecycle commands: Sparkplug `DCMD.redcon` over MQTT/WSS
- board control at REDCON `1`: MCP over the `txing.mcp.v1` WebRTC data channel
  on the board video KVS session
- board control at REDCON `2`: MCP over MQTT/WSS when the daemon advertises
  MQTT-only MCP because video is unavailable/not ready
- board active control: keyboard/drive input does not take over from another
  active session; the unit panel exposes an explicit take-control action
- board video: AWS KVS WebRTC

The app expects `capabilities` to include `sparkplug` and uses it to decide which named shadows should exist for a selected thing.

For `unit` devices, the Rust unit daemon publishes retained
`txings/<device_id>/capability/v2/state` messages for `board`, `mcp`, and
`video`. Sparkplug projection reflects those into the capability stack; `video`
becomes enabled only when the native KVS worker is ready.

The office app must not derive board/MCP/video availability locally from pending
commands or client-side transport state. Capability indicators reflect the
Sparkplug named shadow projection. A small delay is acceptable; inconsistent
client-side capability prediction is not.

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
- the Cognito stack outputs

The office bundle version is injected by Vite from the root `VERSION` file during
the build. It is not a Cloudflare environment variable.

Local Cognito sign-in remains allowed for:

- `http://localhost:5173/`
- `http://127.0.0.1:5173/`

## Cloudflare Pages

```bash
just office::build
```

Production deployment is a Cloudflare Pages Git deployment, not an AWS S3 or
CloudFront upload. Use these Cloudflare Pages settings:

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
  - `VITE_ADMIN_EMAIL`

`office/public/_redirects` keeps deep SPA routes on `index.html` when served by
Cloudflare Pages. `just office::deploy` is now informational and prints the
Cloudflare Pages settings.

## Public Sign-In Entry

The public `txing.dev` site is a separate Cloudflare Pages project under
`www/`. Its sign-in link points to `https://office.txing.dev/?signin=1`.
The office SPA consumes that query parameter, starts the existing PKCE Cognito
flow from the office origin, and Cognito returns to `https://office.txing.dev/`.
Do not add `txing.dev` as a Cognito callback URL for this entry flow.
Production sign-off redirects through Cognito to `https://txing.dev/`; local
development sign-off returns to the current local office origin.

AWS bootstrap, admin-user creation, and teardown live in [aws.md](../aws.md).
