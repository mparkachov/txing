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

The app expects `capabilitiesSet` to include `sparkplug` and uses it to decide which named shadows should exist for a selected thing.

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
- optional legacy compatibility values for the current device and rig

## Publish

```bash
just web::build
just web::publish
```

`web::publish` uploads `web/dist`, marks HTML as non-cacheable, and invalidates CloudFront.

AWS bootstrap, admin-user creation, and teardown live in [aws.md](../aws.md).
