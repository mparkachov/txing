# txing web admin

SPA shell for browsing town rigs and registered devices, then reading the selected device Thing Shadow and publishing lifecycle commands.

## Scope (v1)

- Static SPA built with Vite, stored in S3, and served through the stack-managed CloudFront URL.
- Cognito native authentication via hosted UI (email + password).
- After sign-in, the SPA exchanges the Cognito ID token for temporary AWS credentials through a Cognito Identity Pool.
- The primary operator routes are:
  - `/<town>` -> rig list
  - `/<town>/<rig>` -> device list
  - `/<town>/<rig>/<device>` -> device detail
  - `/<town>/<rig>/<device>/video` -> device-scoped board video viewer
- Thing Shadow reads and reflection updates go directly from the SPA to AWS IoT Core over MQTT/WSS with SigV4-signed websocket handshakes.
- Lifecycle on/off writes publish Sparkplug `DCMD.redcon` over the same MQTT/WSS connection.
- On first use, the SPA attaches the stack-managed AWS IoT policy to the authenticated Cognito identity.
- The browser MQTT client ID uses the Cognito identity ID plus a per-session suffix so multiple tabs or dev remounts do not collide on the same AWS IoT client ID.
- The SPA lists available rig thing groups and thing names directly from AWS IoT Core with Cognito-backed browser credentials.
- Town drilldown cards use AWS IoT thing-group descriptions, and rig drilldown cards prefer `attributes.deviceName` over raw `device_id` labels.
- Current transport split:
  - classic Thing Shadow is the UI read path over MQTT/WSS
  - lifecycle commands use Sparkplug `DCMD.redcon` over MQTT/WSS
  - board remote API uses MCP over MQTT/WSS under `txings/<device_id>/mcp/...`
  - web discovers MCP via Sparkplug `services/mcp/*` summary metrics and retained MCP descriptor/status topics
  - board video uses KVS WebRTC signaling from `/<town>/<rig>/<device>/video`
  - Cognito hosted UI redirects, Cognito `/oauth2/token`, Cognito Identity, IoT `AttachPolicy`, and IoT `DescribeEndpoint` still use HTTPS
- Default identity:
  - configured town comes from `config/rig.env`
  - direct `/<town>/<rig>/<device>` routes choose the active rig and device at runtime
  - `VITE_DEVICE_THING_NAME` and `VITE_SPARKPLUG_EDGE_NODE_ID` remain optional legacy values only

## Prerequisites

- Bun 1.3+.
- AWS account in `eu-central-1`.

## Local development

1. Install dependencies:

```bash
just web::install
```

2. Preferred: generate env from stack outputs (after infra deploy):

```bash
just web::write-env
```

Manual alternative:

```bash
cp web/.env.example web/.env.local
```

Then fill `web/.env.local`:

- `VITE_AWS_REGION`
- `VITE_SPARKPLUG_GROUP_ID`
- `VITE_COGNITO_DOMAIN`
- `VITE_COGNITO_CLIENT_ID`
- `VITE_COGNITO_USER_POOL_ID`
- `VITE_COGNITO_IDENTITY_POOL_ID`
- `VITE_IOT_POLICY_NAME`
- `VITE_ADMIN_EMAIL`
- optional legacy compatibility:
  - `VITE_DEVICE_THING_NAME`
  - `VITE_SPARKPLUG_EDGE_NODE_ID`

The SPA derives the Cognito callback/logout URL from the page it is currently loaded from, so no deployed redirect URI env vars are needed.
The SPA now resolves the AWS IoT Data-ATS endpoint dynamically at runtime with Cognito-backed AWS credentials, so no endpoint env var is required.
When the browser lands on `/` after sign-in, it canonicalizes to the configured town route from `VITE_SPARKPLUG_GROUP_ID`.

3. Start Vite:

```bash
just web::dev
```

Typical local test flow:

```bash
just aws::deploy
just aws::create-admin-user '<strong-password>'
just web::write-env
just web::dev
```

These commands read `AWS_COGNITO_DOMAIN_PREFIX`, `AWS_ADMIN_EMAIL`, and `AWS_TOWN_PROFILE` from `config/aws.env`.

If you have stale local auth state after callback or token-flow changes, clear the session storage in the browser console and sign in again:

```js
sessionStorage.clear()
location.reload()
```

## CloudFormation

Template location:

- `shared/aws/template.yaml` (single stack for IoT + web admin infra)

Deploy command:

```bash
just aws::deploy
```

Create or update the admin user password:

```bash
just aws::create-admin-user '<strong-password>'
```

After deploy, generate local Vite env automatically:

```bash
just web::write-env
```

This writes `web/.env.local` from stack outputs plus the configured town from `config/rig.env`, and it keeps writing the current device / rig identity as optional legacy compatibility values.

Relevant outputs:

- `WebAppUrl` -> generated CloudFront URL for the deployed SPA
- `WebCognitoDomain` -> `VITE_COGNITO_DOMAIN`
- `WebCognitoUserPoolId` -> `VITE_COGNITO_USER_POOL_ID`
- `WebCognitoUserPoolClientId` -> `VITE_COGNITO_CLIENT_ID`
- `WebCognitoIdentityPoolId` -> `VITE_COGNITO_IDENTITY_POOL_ID`
- `WebIotPolicyName` -> `VITE_IOT_POLICY_NAME`
- `WebExpectedAdminEmail` -> `VITE_ADMIN_EMAIL`

`web::write-env` writes `VITE_AWS_REGION`, `VITE_SPARKPLUG_GROUP_ID`, and the Cognito stack outputs. It also keeps writing `VITE_DEVICE_THING_NAME` and `VITE_SPARKPLUG_EDGE_NODE_ID` as optional legacy compatibility values only. The app resolves the AWS IoT Data-ATS endpoint dynamically at runtime and reuses it for both shadow and Sparkplug MQTT/WSS connections.

## Video URL schema

- Canonical board video route: `/<town>/<rig>/<device>/video`
- `town` must match the deployment-scoped `VITE_SPARKPLUG_GROUP_ID`
- `rig` is the AWS IoT dynamic thing-group name and Sparkplug edge node id
- `device` is the AWS IoT thing name / stable `device_id`
- The SPA computes this route from current device assignment and web origin; it is not configured in stack outputs, board env files, or Thing Shadow
- The KVS signaling channel is also computed from the device id: `<device_id>-board-video`

On the first MQTT shadow connect after a new sign-in, the SPA may briefly retry while the IoT policy attachment propagates for the Cognito identity.
The current implementation still performs HTTPS auth/bootstrap calls after sign-in for Cognito token refresh, Cognito Identity, and IoT policy attachment; the live shadow view and Sparkplug command transport use MQTT/WSS.
If you update from an older stack, redeploy `shared/aws/template.yaml` so the web IoT policy allows the per-session MQTT client ID suffix. Until that policy change is deployed, the SPA falls back to the legacy exact identity client ID for compatibility, which means overlapping tabs can still evict each other.
The same stack redeploy is also required for the authenticated Cognito role to gain `ListThingGroups`, `DescribeThingGroup`, and `ListThingsInThingGroup` for the new rig / device browser pages.

## Deploy the SPA

Build and publish:

```bash
just web::build
just web::publish
```

`web::publish` uploads `web/dist` to the stack output bucket, marks HTML as non-cacheable, and invalidates the CloudFront distribution.

## Hosting note

The stack serves the SPA from CloudFront instead of the raw S3 website endpoint because Cognito hosted UI callback URLs must use HTTPS for non-localhost origins, while S3 website endpoints are HTTP-only.

## Security note

`AdminEmail` is currently enforced in the SPA client only. It is suitable for your single-admin v1, but it is not a hard server-side authorization boundary.

## Lifecycle note

- The UI switch remains a simple on/off control.
- `on` publishes `DCMD.redcon=3`.
- `off` publishes `DCMD.redcon=4`.
- The UI reads lifecycle state from shadow `desired.redcon` and `reported.redcon`.
- The SPA does not write internal desired lifecycle fields such as `desired.board.power`.

## MCP teleop note

- Teleop control uses MCP over MQTT (`txings/<device_id>/mcp/...`) instead of treating raw `cmd_vel` publish as the long-term API.
- The browser acquires and renews an MCP control lease while sending `cmd_vel.publish`.
- A raw `<device_id>/board/cmd_vel` publish fallback remains for compatibility during rollout.
