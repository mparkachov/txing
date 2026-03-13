# `gw` gateway subproject

Python service for the Raspberry Pi 5 gateway.

Responsibilities:
- Connect directly to AWS IoT Core over MQTT/mTLS
- Synchronize classic Thing Shadow for thing `txing`
- Bridge `state.desired.mcu.power` power-state requests to the MCU over BLE rendezvous sessions
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

AWS CLI connectivity must be working (credentials + region via role/env/default config/SSO) with permissions for AWS IoT and AWS IoT Data Plane calls used by this project.
Gateway runtime also needs AWS credentials (default SDK chain) with CloudWatch Logs write permissions for `/txing/gw`.

## Install on a new Raspberry Pi 5 (64-bit OS)

Assumption: latest Raspberry Pi OS 64-bit, user `pi`, clean machine.

1. Install base packages:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y git curl jq awscli bluez just
sudo systemctl enable --now bluetooth
```

2. Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.profile
source ~/.profile
uv --version
```

3. Clone the repository:

```bash
cd ~
git clone <your-repo-url> txing
cd txing
```

4. Ensure AWS connectivity is configured in this shell:

```bash
aws sts get-caller-identity
```

5. Standard procedure: copy existing gateway credentials into `certs/`:

```bash
mkdir -p ~/txing/certs
# Copy these from an existing working gateway host or secure key storage:
# - txing-gw.cert.pem
# - txing-gw.private.key
# - txing-gw.cert.arn
# - iot-data-ats.endpoint
# - AmazonRootCA1.pem
```

6. Validate AWS access and local cert artifacts:

```bash
cd ~/txing
just gw::check
```

This check also validates required local tools (`aws`, `jq`, `uv`, `just`, `openssl`) are installed.

7. Only if rotating certs or provisioning a brand new cert: run bootstrap.
`just aws::bootstrap` generates a new key pair when local cert files are absent; it does not download old private keys from AWS.

```bash
cd ~/txing
just aws::bootstrap
```

8. Install gateway dependencies and verify startup:

```bash
cd ~/txing/gw
uv python install 3.12
uv sync
uv run gw --help
uv run gw --debug
```

9. Optional: run as `systemd` service:

```bash
sudo tee /etc/systemd/system/txing-gw.service >/dev/null <<'EOF'
[Unit]
Description=txing gateway
After=network-online.target bluetooth.target
Wants=network-online.target bluetooth.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/txing/gw
Environment=PATH=/home/pi/.local/bin:/usr/local/bin:/usr/bin
Environment=AWS_REGION=eu-central-1
ExecStart=/home/pi/.local/bin/uv run gw
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now txing-gw
sudo journalctl -u txing-gw -f
```

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
- CloudWatch log group: `/txing/gw` (direct upload from process)

Default logging behavior:
- stdout/journal (`systemd`): only important lifecycle `INFO` + all `WARNING/ERROR`
- CloudWatch Logs (`/txing/gw`): full operational logs (no CloudWatch agent required)
- If CloudWatch preflight fails (missing log group or AWS credentials/permissions mismatch), gateway continues with stdout logging and prints a startup warning. Run `just gw::check`.

Dry-run mode (no BLE writes, still syncs AWS shadow):

```bash
uv run gw --no-ble
```

`--no-ble` is MQTT update-driven (subscribed topics), not fixed-interval cloud polling.

## Set desired power (`just`)

Use `just` recipes (AWS CLI) instead of `uv run wake/sleep`.

From repository root:

```bash
just gw::wake
just gw::sleep
just gw::print
```

From `gw/`:

```bash
just wake
just sleep
just print
```

These recipes call `aws iot-data update-thing-shadow` directly with:
- `state.desired.mcu.power=true` (`wake`, meaning request the wakeup state)
- `state.desired.mcu.power=false` (`sleep`, meaning request the sleep state)
- `get-thing-shadow` (`print`)

Default recipe values:
- thing name: `txing`
- region: `eu-central-1`
- endpoint file: `<repo>/certs/iot-data-ats.endpoint`

Override example:

```bash
just gw::wake thing_name=my-thing region=eu-central-1 endpoint_file=certs/iot-data-ats.endpoint
```

`print` prints the current real AWS Thing Shadow document.

## Runtime behavior

- Terminology:
  - `power=true` means the MCU is in the wakeup state.
  - `power=false` means the MCU is in the sleep state with periodic `5 s` rendezvous wakeups and brief advertising windows.
- Operates in event-driven mode from MQTT subscriptions (no fixed-interval cloud polling).
- Subscribes to:
  - `$aws/things/<thing>/shadow/get/accepted`
  - `$aws/things/<thing>/shadow/update/delta`
- On startup, requests full shadow with `$aws/things/<thing>/shadow/get`.
- Loads BLE UUIDs from `state.reported.mcu.ble.*` and validates them against the peripheral during short rendezvous sessions.
- Uses optional `state.reported.mcu.ble.deviceId` as the primary scan match for fast reconnect.
- Keeps a scanner running while disconnected and treats disconnects as normal behavior.
- While the MCU is in the sleep state, stays disconnected by default, watches the periodic advertisements to maintain BLE presence, and reconnects during a rendezvous window only when a BLE session is needed.
- While the MCU is in the wakeup state, maintains a live BLE session when possible.
- Uses one canonical 3-byte MCU State Report (`sleep flag` + `batteryMv`) from both BLE paths:
  - advertising manufacturer data while disconnected
  - GATT reads/notifications while connected
- Publishes BLE connection state at `state.reported.mcu.ble.online`:
  - `true` only after sustained BLE presence has been confirmed
  - remains `true` while the device is connected or keeps advertising within the presence timeout
  - becomes `false` only after the configured presence timeout expires without a matching connection or advertisement
- If UUIDs are missing/invalid or do not match GATT, enters BLE UUID search mode and discovers UUIDs from service/characteristic properties.
- Processes desired power from cloud (`state.desired.mcu.power`).
- For `power=true`, waits for the next advertisement if disconnected, connects, writes the wakeup-state command, polls for acknowledgement, and then keeps the BLE session available until a normal disconnect occurs.
- For `power=false`, if connected, writes the sleep-state command and lets the MCU return to its periodic `5 s` rendezvous behavior; if already disconnected, it does not force a reconnect.
- Updates `state.reported.mcu.batteryMv` only when the observed MCU battery value changes, so the AWS shadow metadata timestamp for `batteryMv` tracks real battery changes instead of unrelated BLE state publishes.
- Publishes reported updates to AWS:
  - `state.reported.mcu.power`
  - `state.reported.mcu.batteryMv`
  - `state.reported.mcu.ble.serviceUuid`
  - `state.reported.mcu.ble.sleepCommandUuid`
  - `state.reported.mcu.ble.stateReportUuid`
  - `state.reported.mcu.ble.online`
  - `state.reported.mcu.ble.deviceId` (when known)
- Clears desired when reported matches by publishing `desired.mcu.power=null`.
- Mirrors current local state into `/tmp/txing_shadow.json`.
- Enforces single instance lock at `/tmp/txing_gw.lock` (override with `--lock-file`).

## Useful options

```bash
uv run gw --help
```

Common overrides:
- `--thing-name txing`
- `--scan-timeout 12`
- `--connect-timeout 5`
- `--command-ack-timeout 1`
- `--command-ack-poll-interval 0.1`
- `--device-stale-after 0.75`
- `--scan-mode active`
- `--iot-endpoint <host>`
- `--iot-endpoint-file ../certs/iot-data-ats.endpoint`
- `--cert-file ../certs/txing-gw.cert.pem`
- `--key-file ../certs/txing-gw.private.key`
- `--ca-file ../certs/AmazonRootCA1.pem`
- `--client-id txing-gw-pi5`
- `--debug` (verbose stdout logging)
- `--cloudwatch-log-group /txing/gw`
- `--cloudwatch-log-stream <stream-name>`
- `--cloudwatch-region <aws-region>` (override region; default inferred from IoT endpoint)
- `--no-cloudwatch-logs`
