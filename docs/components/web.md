# Web

The web app is the operator and admin SPA for browsing towns, rigs, and devices, reading the current projected state, opening board video, and sending lifecycle and MCP actions.

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

The video route is derived from the selected route and web origin. It is not stored in Thing Shadow or board config.

## Current Transport Split

- route breadcrumbs and first-load metadata: AWS IoT HTTPS APIs
- live shadow updates: named Thing Shadow over MQTT/WSS
- lifecycle commands: Sparkplug `DCMD.redcon` over MQTT/WSS
- board control: MCP over MQTT/WSS, with WebRTC data-channel preference when advertised
- board video: AWS KVS WebRTC

The app expects `capabilities` to include `sparkplug` and uses it to decide which named shadows should exist for a selected thing.

## Local Development

Install and write the local env:

```bash
just web::install
just web::write-env
just web::dev
```

Manual fallback:

```bash
cp web/.env.example web/.env.local
```

`web::write-env` writes:

- `VITE_AWS_REGION`
- `VITE_TOWN_THING_NAME`
- `VITE_SPARKPLUG_GROUP_ID`
- the Cognito stack outputs

The web bundle version is injected by Vite from the root `VERSION` file during
the build. It is not a Cloudflare environment variable.

Local Cognito sign-in remains allowed for:

- `http://localhost:5173/`
- `http://127.0.0.1:5173/`

## Cloudflare Pages

```bash
just web::build
```

Production deployment is a Cloudflare Pages Git deployment, not an AWS S3 or
CloudFront upload. Use these Cloudflare Pages settings:

- Project: `txing-office`
- Root directory: `web`
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

`web/public/_redirects` keeps deep SPA routes on `index.html` when served by
Cloudflare Pages. `just web::deploy` is now informational and prints the
Cloudflare Pages settings.

## Public Sign-In Entry

The public `thing.dev` site is a separate Cloudflare Pages project under
`site/`. Its sign-in link points to `https://office.txing.dev/?signin=1`.
The office SPA consumes that query parameter, starts the existing PKCE Cognito
flow from the office origin, and Cognito returns to `https://office.txing.dev/`.
Do not add `thing.dev` as a Cognito callback URL for this entry flow.

AWS bootstrap, admin-user creation, and teardown live in [aws.md](../aws.md).
