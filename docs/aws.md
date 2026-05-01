# AWS

This guide covers fresh AWS bring-up, runtime registration, shadow reset, and destructive rebuild back to an empty account state.

Prefer the AWS CLI for control-plane work. The `just aws-town ...`, `just aws-rig ...`, and `just aws-device ...` recipes are thin wrappers around `aws` with the repo-local profile setup applied.

## Local Config Files

Initialize and edit:

```bash
cp config/aws.env.example config/aws.env
cp config/aws.credentials.example config/aws.credentials
cp config/aws.config.example config/aws.config
cp config/rig.env.example config/rig.env
cp config/board.env.example config/board.env
```

Shared files:

- `config/aws.env`
  - `AWS_REGION`
  - `AWS_STACK_NAME`
  - `AWS_COGNITO_DOMAIN_PREFIX`
  - `AWS_ADMIN_EMAIL`
- `config/aws.credentials`
  - `[town]` access keys for the owning AWS account
- `config/aws.config`
  - `[profile rig].role_arn = <RigRuntimeRoleArn>`
  - `[profile device].role_arn = <DeviceRuntimeRoleArn>`

Host-specific files:

- `config/rig.env`
  - `SPARKPLUG_GROUP_ID`
  - `RIG_NAME`
- `config/board.env`
  - `THING_NAME`
  - `BOARD_VIDEO_REGION`
  - `BOARD_VIDEO_SENDER_COMMAND`

## Fresh Bring-Up

### 1. Deploy The Shared Stack

```bash
just aws::deploy
just aws::describe
```

The shared stack owns:

- IAM roles and policies for the runtimes and web app
- Greengrass token exchange role, AWS IoT role alias, and artifact bucket
- Cognito resources
- CloudFront and S3 for the SPA
- stack-owned IoT thing types `town` and `rig`

Rig Greengrass component recipe templates live in `rig/greengrass/recipes`; the
root of the repository does not own a separate Greengrass package.

### 2. Deploy Witness

Witness is a separate stack:

```bash
just witness::deploy
```

It owns:

- the Sparkplug witness Lambda
- the witness IAM role
- the witness log group
- the IoT topic rule that projects Sparkplug into the `sparkplug` named shadow

### 3. Configure Thing Indexing

```bash
just aws::configure-indexing
```

This enables registry indexing plus AWS IoT connectivity status indexing
(`thingConnectivityIndexingMode=STATUS`). The stack template defines the IAM,
role-alias, and policy resources, but AWS IoT fleet indexing itself is configured
through the AWS IoT `UpdateIndexingConfiguration` API.

Current searchable registry attributes:

- `attributes.name`
- `attributes.town`
- `attributes.rig`

`attributes.shortId` and `attributes.capabilitiesSet` remain non-searchable metadata.

### 4. Register Town, Rig, And Devices

```bash
just aws::register-town town
just aws::register-rig town rig
just aws::register-device town rig unit
```

Current capabilities come from
[`shared/aws/thing-type-capabilities.json`](../shared/aws/thing-type-capabilities.json):

- `town` -> `sparkplug`
- `rig` -> `sparkplug`
- `unit` -> `sparkplug,mcu,board,mcp,video`

Notes:

- there is no `device` named shadow
- `register-device` also creates the per-device KVS signaling channel
- registration seeds the named shadows from `devices/<thing-type>/aws/default-<shadow>-shadow.json`

### 5. Create The Web Admin User

```bash
just aws::create-admin-user '<strong-password>'
```

### 6. Generate And Publish The SPA

```bash
just web::write-env
just web::build
just web::publish
```

`web::write-env` resolves the current stack outputs and writes `web/.env.local`.

### 7. Validate Runtime Access

```bash
just rig::check
just board::check
```

## Shadow Inspection And Reseed

Inspect the named shadows required by a thing's `attributes.capabilitiesSet`:

```bash
just aws::shadow <thing>
just aws::shadow <thing> sparkplug
```

Reset the advertised named shadows:

```bash
just aws::shadow-reset <thing>
just aws::shadow-reset <thing> sparkplug
```

Current behavior:

- unit things reseed `sparkplug`, `mcu`, `board`, `mcp`, and `video`
- rig and town things reseed only `sparkplug`
- the reset path deletes the classic unnamed shadow and removes known named shadows that are not valid for the thing's current `capabilitiesSet`

Use this after manual power cuts or when you want to force the runtime mirrors back to their default offline state.

## Complete Cleanup And Re-Create From Scratch

This is the destructive path back to an empty AWS state.

### 1. Stop All Runtimes

Stop `rig` and every `board` instance first so they do not immediately recreate registry state or retained topics while you are deleting resources.

### 2. Delete Registered Things

Delete:

- all `town-*` things
- all `rig-*` things
- all device things such as `unit-*`

Use the AWS CLI directly if you are doing a full teardown sweep:

```bash
just aws-town iot list-things --output table
just aws-town iot delete-thing --thing-name <thing-name>
```

### 3. Delete Dynamic Thing Groups

Delete the runtime-created thing groups:

- the town group, for example `town`
- each rig group, for example `rig`

```bash
just aws-town iot list-thing-groups --output table
just aws-town iot delete-dynamic-thing-group --thing-group-name <group-name>
```

### 4. Delete Device KVS Signaling Channels

Each registered device creates a signaling channel named `<device-id>-board-video`.

```bash
just aws-town kinesisvideo list-signaling-channels --output table
just aws-town kinesisvideo delete-signaling-channel --channel-arn <channel-arn>
```

### 5. Deprecate Thing Types

Deprecate every type that was used:

- stack-owned: `town`, `rig`
- device types created outside the stack, for example `unit`

```bash
just aws-town iot deprecate-thing-type --thing-type-name town
just aws-town iot deprecate-thing-type --thing-type-name rig
just aws-town iot deprecate-thing-type --thing-type-name unit
```

Wait five minutes after deprecating thing types before deleting the shared stack.

### 6. Delete Witness

Witness is not deleted by `just aws::delete`.

```bash
just aws-town cloudformation delete-stack --stack-name <shared-stack-name>-witness
```

### 7. Delete The Shared Stack

`just aws::delete` empties the current web app and Greengrass artifact buckets
before deleting the shared stack:

```bash
just aws::delete
```

If you delete the stack manually instead, empty both buckets first.

## Rebuild Order After Cleanup

After a destructive cleanup, recreate in this order:

1. `just aws::deploy`
2. `just witness::deploy`
3. `just aws::configure-indexing`
4. `just aws::register-town town`
5. `just aws::register-rig town rig`
6. `just aws::register-device town rig unit`
7. `just aws::create-admin-user '<strong-password>'`
8. `just web::write-env`
9. `just web::build`
10. `just web::publish`
