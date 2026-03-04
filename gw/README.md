# `gw` gateway subproject

Python service for the Raspberry Pi 5 gateway.

Responsibilities:
- Connect directly to AWS IoT Core over MQTT/mTLS
- Synchronize classic Thing Shadow for thing `txing`
- Bridge `state.desired.mcu.power` commands to MCU over BLE
- Publish MCU state to `state.reported.mcu.*`

Shadow contract source of truth:
- `../docs/txing-shadow.schema.json`
- `../docs/device-gateway-shadow-spec.md`
- Design decision: `gw` owns and evolves the `mcu.*` shadow subtree contract.

High-level architecture:
- AWS IoT Device Shadow -> MQTT -> gw -> BLE -> mcu

## Requirements

The system requires these tools installed:
- `uv`
- `just`
- `jq`
- `aws` (AWS CLI)

AWS CLI must also be configured (credentials/profile + region) with permissions for AWS IoT and AWS IoT Data Plane calls used by this project.

## Run gateway

Run from `gw/`:

```bash
uv run gw
```

This uses bootstrap artifacts by default:
- endpoint file: `../certs/iot-data-ats.endpoint`
- cert: `../certs/txing-gw.cert.pem`
- private key: `../certs/txing-gw.private.key`
- root CA: `../certs/AmazonRootCA1.pem`

Dry-run mode (no BLE writes, still syncs AWS shadow):

```bash
uv run gw --no-ble
```

## Set desired power (`just`)

From `gw/`, use `just` recipes (AWS CLI) instead of `uv run wake/sleep`:

```bash
just wake
just sleep
just print
```

These recipes call `aws iot-data update-thing-shadow` directly with:
- `state.desired.mcu.power=true` (`wake`)
- `state.desired.mcu.power=false` (`sleep`)
- `get-thing-shadow` (`print`)

Default recipe values:
- thing name: `txing`
- region: `eu-central-1`
- endpoint file: `../certs/iot-data-ats.endpoint`

Override example:

```bash
just wake thing_name=my-thing region=eu-central-1 endpoint_file=../certs/iot-data-ats.endpoint
```

`just print` prints the current real AWS Thing Shadow document.

## Runtime behavior

- Subscribes to:
  - `$aws/things/<thing>/shadow/get/accepted`
  - `$aws/things/<thing>/shadow/update/delta`
- On startup, requests full shadow with `$aws/things/<thing>/shadow/get`.
- Processes desired power from cloud (`state.desired.mcu.power`).
- Sends BLE Sleep Command:
  - `power=true` -> `sleep=false` (`0x00`)
  - `power=false` -> `sleep=true` (`0x01`)
- Publishes reported updates to AWS:
  - `state.reported.mcu.power`
  - `state.reported.mcu.batteryPercent`
- Clears desired when reported matches by publishing `desired.mcu.power=null`.
- Mirrors current local state into `/tmp/txing_shadow.json`.
- Enforces single instance lock at `/tmp/txing_gw.lock` (override with `--lock-file`).

## Useful options

```bash
uv run gw --help
```

Common overrides:
- `--thing-name txing`
- `--iot-endpoint <host>`
- `--iot-endpoint-file ../certs/iot-data-ats.endpoint`
- `--cert-file ../certs/txing-gw.cert.pem`
- `--key-file ../certs/txing-gw.private.key`
- `--ca-file ../certs/AmazonRootCA1.pem`
- `--client-id txing-gw-pi5`
