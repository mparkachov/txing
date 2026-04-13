# txing development

For a high-level device overview, see [README.md](./README.md).

Monorepo root for `txing`.

- MCU firmware lives in `mcu/` (Rust).
- Rig software lives in `rig/` (Python, direct AWS IoT MQTT + BLE bridge).
- Device-side Raspberry Pi reporter lives in `board/` (Python, direct AWS IoT MQTT shadow reporting).
- Web admin SPA lives in `web/` (React + Vite).
- Shared docs live in `docs/`.
- Thing Shadow contract schema lives in `docs/txing-shadow.schema.json`.
- Thing Shadow guidance lives in `docs/thing-shadow.md`.
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
Use `just aws-txing ...` for AWS CLI commands with the txing endpoint runtime profile.

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
just aws::shadow
just aws::shadow-reset
```

`aws::shadow-reset` deletes the current classic shadow document and reseeds it from `shared/aws/default-shadow.json`, which represents the clean offline/powered-down state with stale desired power requests removed.

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
