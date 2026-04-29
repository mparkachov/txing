# txing development

For a high-level device overview, see [README.md](./README.md).

Monorepo root for `txing`.

- MCU firmware for the current `unit` device type lives in `devices/unit/mcu/` (Rust).
- Rig software lives in `rig/` (Python, direct AWS IoT MQTT + BLE bridge).
- Device-side Raspberry Pi reporter for the current `unit` device type lives in `devices/unit/board/` (Python, direct AWS IoT MQTT shadow reporting).
- Web admin SPA lives in `web/` (React + Vite).
- Shared docs live in `docs/`.
- Named Thing Shadow contract schemas for the current `unit` device type live in `devices/unit/aws/*-shadow.schema.json`.
- Thing Shadow guidance for the current `unit` device type lives in `devices/unit/docs/thing-shadow.md`.
- High-level paths:
  - `AWS IoT Device Shadow -> MQTT -> rig -> BLE -> mcu`
  - `AWS IoT Device Shadow -> MQTT -> board`

## System requirements

For Python/AWS workflows in this repository, install and configure:
- `uv`
- `just`
- `jq`
- `aws` (AWS CLI)

The default repo workflow keeps AWS CLI config inside `config/` in the checkout.
Copy `config/aws.env.example` to `config/aws.env`, `config/aws.credentials.example` to `config/aws.credentials`, and `config/aws.config.example` to `config/aws.config`, then edit those files for your town/account.
If you are working on the rig runtime, also copy `config/rig.env.example` to `config/rig.env` and edit the rig-local runtime settings there.
If you are working on the device-side board runtime, also copy `config/board.env.example` to `config/board.env` and edit the board-local runtime settings there.
Use `just aws-rig ...` for AWS CLI commands with the project rig/runtime profile and `just aws-town ...` for AWS CLI commands with the direct town account profile.
Use `just aws-device ...` for AWS CLI commands with the device endpoint runtime profile.

## Task Runner

This monorepo standardizes on `just` as the task runner.

Run from repository root:

```bash
just --list
just rig::wake
just board::run
just aws::shadow
just aws::shadow-reset
just mcu::build
just web::dev
just web::write-env
```

Subproject `justfile`s are included by the root `justfile` as modules:
- `rig::...` -> `rig/justfile`
- `board::...` -> `board/justfile`
- `aws::...` -> `shared/aws/justfile`
- `mcu::...` -> `mcu/justfile`
- `web::...` -> `web/justfile`

Firmware example:

```bash
just mcu::build
```

Rig example:

```bash
cd rig
just run
```

Board example:

```bash
cd board
uv run board --once
```

AWS stack deploy example (single stack with IoT + web admin):

```bash
just aws::deploy
```

That uses `AWS_COGNITO_DOMAIN_PREFIX`, `AWS_ADMIN_EMAIL`, and `AWS_TOWN_PROFILE` from `config/aws.env`.

Inspect or reset the live Thing Shadow from the repository root:

```bash
just aws::shadow <thing>
just aws::shadow-reset <thing>
```

`aws::shadow <thing>` lists the named shadows advertised by the thing's non-searchable `attributes.capabilitiesSet`. Unit things expose `sparkplug`, `device`, `mcu`, `board`, and `video`; rig and town things expose only `sparkplug`.

`aws::shadow-reset <thing>` deletes the classic unnamed shadow, removes known named shadows that are not valid for the thing's `capabilitiesSet`, and reseeds the advertised named shadows. Unit things use `devices/<type>/aws/default-<shadow>-shadow.json`; rig and town things reseed only `sparkplug`. Pass `<shadow>` as the second positional argument to reset one valid named shadow only.

The web admin does not use API Gateway. After Cognito sign-in, the SPA exchanges the user pool token for temporary AWS credentials through a Cognito Identity Pool and calls AWS IoT Thing Shadow directly.

Typical local web test flow:

```bash
just aws::deploy
just aws::create-admin-user '<strong-password>'
just web::write-env
just web::dev
```

Publish the web SPA after building it:

```bash
just web::build
just web::publish
```

Set the admin password in Cognito:

```bash
just aws::create-admin-user '<strong-password>'
```
