# txing

Monorepo root for `txing`.

- MCU firmware lives in `mcu/` (Rust).
- Gateway software lives in `gw/` (Python, direct AWS IoT MQTT + BLE bridge).
- Web admin SPA lives in `web/` (React + Vite).
- Shared docs live in `docs/`.
- Thing Shadow contract schema lives in `docs/txing-shadow.schema.json`.
- Thing Shadow guidance lives in `docs/thing-shadow.md`.
- High-level path: `AWS IoT Device Shadow -> MQTT -> gw -> BLE -> mcu`.

## System requirements

For gateway workflows in this repository, install and configure:
- `uv`
- `just`
- `jq`
- `aws` (AWS CLI)

AWS CLI must be configured with credentials/profile and region.

## Task Runner

This monorepo standardizes on `just` as the task runner.

Run from repository root:

```bash
just --list
just gw::wake
just aws::bootstrap
just mcu::build
just web::dev
just web::write-env
```

Subproject `justfile`s are included by the root `justfile` as modules:
- `gw::...` -> `gw/justfile`
- `aws::...` -> `aws/justfile`
- `mcu::...` -> `mcu/justfile`
- `web::...` -> `web/justfile`

Firmware example:

```bash
just mcu::build
```

Gateway example:

```bash
cd gw
uv run gw
```

AWS stack deploy example (single stack with IoT + web admin):

```bash
just aws::deploy \
  <unique-cognito-prefix> \
  <admin-email>
```

The web admin does not use API Gateway. After Cognito sign-in, the SPA exchanges the user pool token for temporary AWS credentials through a Cognito Identity Pool and calls AWS IoT Thing Shadow directly.

Typical local web test flow:

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

Publish the web SPA after building it:

```bash
just web::build
just aws::publish-web
```

Set the admin password in Cognito:

```bash
just aws::create-admin-user \
  <admin-email> \
  '<strong-password>'
```
