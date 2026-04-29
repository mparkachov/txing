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
- The SPA lists rigs from the configured town thing group and devices from rig thing groups directly from AWS IoT Core with Cognito-backed browser credentials.
- Town and rig drilldown cards prefer IoT registry `attributes.name` over raw thing names.
- Current transport split:
  - named Thing Shadow is the UI read path over MQTT/WSS
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

## Project-Local Config Files

The project-local flow expects these local files under `config/`:

```bash
cp config/aws.env.example config/aws.env
cp config/rig.env.example config/rig.env
cp config/board.env.example config/board.env        # only for board hosts
cp config/aws.credentials.example config/aws.credentials
cp config/aws.config.example config/aws.config
```

Adjust these `config/*.env` parameters before bootstrap:

- `config/aws.env`
  - `AWS_REGION`: AWS region for the deployment and runtimes.
  - `AWS_STACK_NAME`: CloudFormation stack name. Keep this aligned with the deployed stack, for example `town`.
  - `AWS_COGNITO_DOMAIN_PREFIX`: hosted Cognito domain prefix. This must be globally unique per region/account combination used by Cognito.
  - `AWS_ADMIN_EMAIL`: admin email used by `aws::create-admin-user` and written into the SPA config.
  - `AWS_TOWN_PROFILE`: direct AWS CLI profile for the owning account. Usually keep `town`.
  - `AWS_RIG_PROFILE`: local profile used by rig hosts. Usually keep `rig`.
  - `AWS_DEVICE_PROFILE`: local profile used by device/board hosts. Usually keep `device`.
  - `AWS_SHARED_CREDENTIALS_FILE`: change only if you are not using `config/aws.credentials`.
  - `AWS_CONFIG_FILE`: change only if you are not using `config/aws.config`.
- `config/rig.env`
  - `SPARKPLUG_GROUP_ID`: town slug and Sparkplug group id. This must match the registered town name and the web deployment scope.
  - `RIG_NAME`: rig slug and Sparkplug edge node id. This must match the registered rig name and dynamic rig thing group name.
  - `CLOUDWATCH_LOG_GROUP`: change only if you want a non-default rig log group.
- `config/board.env` when provisioning a board host
  - `THING_NAME`: registered device thing name, for example `unit-abc123`.
  - `BOARD_VIDEO_REGION`: board video AWS region. Usually the same as `AWS_REGION`.
  - `BOARD_VIDEO_SENDER_COMMAND`: absolute path to the native KVS sender binary on the board host.
  - `KVS_DUALSTACK_ENDPOINTS`: keep `ON` unless you intentionally want to disable dual-stack KVS endpoint resolution.
  - `BOARD_DRIVE_CMD_RAW_MIN_SPEED` / `BOARD_DRIVE_CMD_RAW_MAX_SPEED`: adjust for the measured usable motor range on the chassis.
  - `BOARD_DRIVE_RAW_MAX_SPEED`, `BOARD_DRIVE_PWM_*`, and `BOARD_DRIVE_*`: adjust only if the motor driver wiring or hardware layout differs from the current default chassis.

`config/aws.credentials` and `config/aws.config` are not `*.env` files, but they must also be edited:

- `config/aws.credentials`: fill the `[town]` access key pair for the owning AWS account.
- `config/aws.config`
  - `[profile town].region`
  - `[profile rig].role_arn`: set this to the deployed stack output `RigRuntimeRoleArn`
  - `[profile device].role_arn`: set this to the deployed stack output `DeviceRuntimeRoleArn`

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
just aws::configure-indexing
just aws::register-town town
just aws::register-rig town rig
just aws::register-device town rig unit
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

### Bootstrap A New AWS Environment

From an empty account state, the current manual bootstrap sequence is:

```bash
just aws::deploy
just aws::create-admin-user '<strong-password>'
just aws::configure-indexing
just aws::register-town town
just aws::register-rig town rig
just aws::register-device town rig unit
just web::write-env
just web::build
just web::publish
```

Notes:

- `aws::deploy` creates the stack-owned IAM, Cognito, CloudFront, S3, IoT policies, and the stack-owned `town` and `rig` thing types.
- `aws::configure-indexing` must run once after stack deploy. The current searchable/indexed subset is:
  - `attributes.name` on all thing types
  - `attributes.town` on `rig` and device things
  - `attributes.rig` on device things
- `attributes.shortId` and `attributes.capabilitiesSet` remain registry metadata only; they are not part of the searchable/indexed surface.
- `aws::register-town`, `aws::register-rig`, and `aws::register-device` create the actual registry objects and reported-only shadows. `register-device` also creates the per-device KVS signaling channel.
- `web::publish` is required if you want the stack output `WebAppUrl` to serve the current SPA build. `aws::deploy` alone does not upload `web/dist`.

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

## Full Deletion

For a destructive rebuild back to an empty state, delete non-stack IoT objects first, then delete the stack.

Recommended order:

1. Stop rig and board runtimes so they do not recreate registry state while you are deleting it.
2. Delete all registered IoT things:
   - all `town-*` things
   - all `rig-*` things
   - all device things such as `unit-*`
3. Delete all dynamic thing groups:
   - the town group, for example `town`
   - each rig group, for example `rig`
4. Delete any per-device KVS signaling channels if you want a true empty environment.
5. Empty the stack web app S3 bucket before deleting the stack. `just aws::delete` already does this for the current stack output bucket, but a manual teardown must do the same.
6. Deprecate every IoT thing type and wait 5 minutes before stack deletion:
   - stack-owned thing types: `town`, `rig`
   - device thing types created outside the stack, for example `unit`
7. Delete the stack:

```bash
just aws::delete
```

If you need to deprecate thing types manually with AWS CLI, use:

```bash
aws iot deprecate-thing-type --thing-type-name town
aws iot deprecate-thing-type --thing-type-name rig
aws iot deprecate-thing-type --thing-type-name unit
```

Wait 5 minutes after deprecating thing types before deleting the stack. AWS IoT thing type deletion is not immediate, and stack deletion can fail if those resources are still considered active.

## Hosting note

The stack serves the SPA from CloudFront instead of the raw S3 website endpoint because Cognito hosted UI callback URLs must use HTTPS for non-localhost origins, while S3 website endpoints are HTTP-only.

## Security note

`AdminEmail` is currently enforced in the SPA client only. It is suitable for your single-admin v1, but it is not a hard server-side authorization boundary.

## Lifecycle note

- The UI switch remains a simple on/off control.
- `on` publishes `DCMD.redcon=3`.
- `off` publishes `DCMD.redcon=4`.
- The UI reads lifecycle state from `namedShadows.sparkplug.state.reported.metrics.redcon` and treats pending commands as local browser state until the projected posture converges.
- The SPA does not use or write `state.desired`.

## MCP teleop note

- Teleop control uses board MCP as the only remote board control API.
- MQTT discovery and MQTT MCP (`txings/<device_id>/mcp/...`) remain the fallback for every MCP-capable device.
- When the retained MCP descriptor advertises `webrtc-datachannel`, the browser tries the existing `<device_id>-board-video` KVS channel with data-channel label `txing.mcp.v1` before MQTT.
- Direct host IPv6 and AWS TURN relay both count as WebRTC success; ICE chooses the candidate pair.
- The browser acquires and renews an MCP control lease while sending `cmd_vel.publish`.
- The browser reads current motion/video/control state from MCP `robot.get_state`.
