# txing web admin

SPA for reading the `txing` Thing Shadow and publishing phase-1 lifecycle commands.

## Scope (v1)

- Static SPA built with Vite, stored in S3, and served through the stack-managed CloudFront URL.
- Cognito native authentication via hosted UI (email + password).
- After sign-in, the SPA exchanges the Cognito ID token for temporary AWS credentials through a Cognito Identity Pool.
- Thing Shadow reads and reflection updates go directly from the SPA to AWS IoT Core over MQTT/WSS with SigV4-signed websocket handshakes.
- Lifecycle on/off writes publish Sparkplug `DCMD.redcon` over the same MQTT/WSS connection.
- On first use, the SPA attaches the stack-managed AWS IoT policy to the authenticated Cognito identity.
- The deployed SPA now also serves a `/video` route for the board AWS WebRTC viewer.
- Current transport split:
  - classic Thing Shadow is the UI read path over MQTT/WSS
  - phase-1 lifecycle commands use Sparkplug `DCMD.redcon` over MQTT/WSS
  - board video uses KVS WebRTC signaling from the `/video` route
  - Cognito hosted UI redirects, Cognito `/oauth2/token`, Cognito Identity, and IoT `AttachPolicy` still use HTTPS
- Default phase-1 identity:
  - txing thing name: `txing`
  - Sparkplug group id: `town`
  - Sparkplug edge node id: `rig`

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
- `VITE_IOT_DATA_ENDPOINT`
- `VITE_TXING_THING_NAME`
- `VITE_SPARKPLUG_GROUP_ID`
- `VITE_SPARKPLUG_EDGE_NODE_ID`
- `VITE_COGNITO_DOMAIN`
- `VITE_COGNITO_CLIENT_ID`
- `VITE_COGNITO_USER_POOL_ID`
- `VITE_COGNITO_IDENTITY_POOL_ID`
- `VITE_IOT_POLICY_NAME`
- `VITE_ADMIN_EMAIL`

The SPA derives the Cognito callback/logout URL from the page it is currently loaded from, so no deployed redirect URI env vars are needed.
`VITE_IOT_DATA_ENDPOINT` remains the single AWS IoT endpoint input; the SPA derives the MQTT/WSS host from that Data-ATS endpoint.

3. Start Vite:

```bash
just web::dev
```

Typical local test flow:

```bash
just aws::deploy \
  <existing-or-new-cognito-prefix> \
  <admin-email>
just aws::create-admin-user \
  <admin-email> \
  '<strong-password>'
just web::write-env
just web::dev
```

If you have stale local auth state after callback or token-flow changes, clear the session storage in the browser console and sign in again:

```js
sessionStorage.clear()
location.reload()
```

## CloudFormation

Template location:

- `aws/template.yaml` (single stack for IoT + web admin infra)

Deploy command:

```bash
just aws::deploy \
  txing-admin-auth-123456789012 \
  <admin-email>
```

Create or update the admin user password:

```bash
just aws::create-admin-user \
  <admin-email> \
  '<strong-password>'
```

After deploy, generate local Vite env automatically:

```bash
just web::write-env
```

This writes `web/.env.local` from stack outputs plus the phase-1 Sparkplug identity defaults.

Relevant outputs:

- `WebAppUrl` -> generated CloudFront URL for the deployed SPA
- `BoardVideoViewerUrl` -> generated CloudFront URL for the `/video` route
- `WebCognitoDomain` -> `VITE_COGNITO_DOMAIN`
- `WebCognitoUserPoolId` -> `VITE_COGNITO_USER_POOL_ID`
- `WebCognitoUserPoolClientId` -> `VITE_COGNITO_CLIENT_ID`
- `WebCognitoIdentityPoolId` -> `VITE_COGNITO_IDENTITY_POOL_ID`
- `WebIotPolicyName` -> `VITE_IOT_POLICY_NAME`
- `WebExpectedAdminEmail` -> `VITE_ADMIN_EMAIL`

`web::write-env` also resolves the AWS IoT Data ATS endpoint and writes it as `VITE_IOT_DATA_ENDPOINT`, plus `VITE_AWS_REGION`, `VITE_TXING_THING_NAME`, `VITE_SPARKPLUG_GROUP_ID`, and `VITE_SPARKPLUG_EDGE_NODE_ID`. The app reuses that endpoint for both shadow and Sparkplug MQTT/WSS connections.

On the first MQTT shadow connect after a new sign-in, the SPA may briefly retry while the IoT policy attachment propagates for the Cognito identity.
The current implementation still performs HTTPS auth/bootstrap calls after sign-in for Cognito token refresh, Cognito Identity, and IoT policy attachment; the live shadow view and Sparkplug command transport use MQTT/WSS.

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

## Phase-1 lifecycle note

- The UI switch remains a simple on/off control.
- `on` publishes `DCMD.redcon=3`.
- `off` publishes `DCMD.redcon=4`.
- The UI reads lifecycle state from shadow `desired.redcon` and `reported.redcon`.
- The SPA does not write `desired.mcu.power` or `desired.board.power`.
