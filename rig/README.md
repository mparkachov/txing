# `rig` lifecycle subproject

Python service for the Raspberry Pi 5 rig runtime.

Responsibilities:
- Connect directly to AWS IoT Core over MQTT/mTLS
- Act as the phase-1 `rig` lifecycle runtime in the same process
- Synchronize classic Thing Shadows for `txing`, `rig`, and `town`
- Accept Sparkplug `DCMD.redcon` lifecycle commands and publish `NBIRTH`/`NDATA`/`DBIRTH`/`DDATA`/`DDEATH`
- Bridge REDCON-driven wakeup-state and sleep-state changes to the MCU over BLE rendezvous sessions
- Publish MCU state to `state.reported.mcu.*`
- Publish derived readiness at top-level `state.reported.redcon`

Shadow contract source of truth:
- `../docs/txing-shadow.schema.json`
- `../docs/device-rig-shadow-spec.md`
- Design decision: `rig` owns and evolves the `mcu.*` shadow subtree contract.

High-level architecture:
- Sparkplug host -> AWS IoT MQTT -> rig -> BLE -> mcu
- rig -> AWS IoT Thing Shadows (`txing`, `rig`, `town`)

## Requirements

The system requires these tools installed:
- `uv`
- `just`
- `jq`
- `aws` (AWS CLI)

AWS CLI connectivity must be working (credentials + region via role/env/default config/SSO) with permissions for AWS IoT and AWS IoT Data Plane calls used by this project.
Rig runtime also needs AWS credentials (default SDK chain) with CloudWatch Logs write permissions for `/town/rig/txing`.

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

5. Standard procedure: copy the shared device AWS IoT credentials into `certs/`:

```bash
mkdir -p ~/txing/certs
# Copy these from an existing working host or secure key storage:
# - txing.cert.pem
# - txing.private.key
# - txing.cert.arn
# - iot-data-ats.endpoint
# - AmazonRootCA1.pem
```

6. Validate AWS access and local cert artifacts:

```bash
cd ~/txing
just rig::check
```

This check also validates required local tools (`aws`, `jq`, `uv`, `just`, `openssl`) are installed.

7. Only if rotating certs or provisioning a brand new cert: run bootstrap.
`just aws::bootstrap` generates the shared `txing.*` key pair when local cert files are absent; it does not download old private keys from AWS.

```bash
cd ~/txing
just aws::bootstrap
```

8. Build the rig runtime with the OS `python3` and verify startup:

```bash
cd ~/txing/rig
python3 --version
just build
./.venv/bin/rig --help
just debug
```

`build` is the normal install step for the rig runtime. It creates or updates `rig/.venv/` from the OS `python3` on `PATH` and installs the packaged entry points there. You do not need to run `sync` first. `rig` requires Python `3.12+`, so make sure `python3 --version` on the host machine satisfies that before running `just build`.

9. Optional: install the `systemd` service:

```bash
cd ~/txing
just rig::install-service
sudo journalctl -u rig -f
```

The `just rig::install-service` task enables `bluetooth`, writes `/etc/systemd/system/rig.service` for the current user and checkout path, reloads `systemd`, and enables `rig`.
It points `ExecStart` at the built rig executable in `rig/.venv/bin/rig`, so run `just rig::build` first.

## Run rig

Run from `rig/`:

```bash
just run
```

This uses bootstrap artifacts by default:
- endpoint file: `../certs/iot-data-ats.endpoint`
- cert: `../certs/txing.cert.pem`
- private key: `../certs/txing.private.key`
- root CA: `../certs/AmazonRootCA1.pem`
- CloudWatch log group: `/town/rig/txing` (direct upload from process)

Default logging behavior:
- stdout/journal (`systemd`): only important lifecycle `INFO` + all `WARNING/ERROR`
- CloudWatch Logs (`/town/rig/txing`): full operational logs (no CloudWatch agent required)
- If CloudWatch preflight fails (missing log group or AWS credentials/permissions mismatch), rig continues with stdout logging and prints a startup warning. Run `just rig::check`.

Dry-run mode (no BLE writes, still syncs AWS shadow and Sparkplug lifecycle traffic):

```bash
./.venv/bin/rig --no-ble
```

`--no-ble` is MQTT update-driven (subscribed topics), not fixed-interval cloud polling.

## Send lifecycle commands (`just`)

Use `just` recipes to publish phase-1 Sparkplug lifecycle commands.

From repository root:

```bash
just rig::wake
just rig::sleep
just rig::print
just aws::shadow
just aws::shadow-reset
```

From `rig/`:

```bash
just build
just wake
just sleep
just dcmd
just ddata
just print
```

These recipes call `rig-sparkplug-cmd` with:
- `DCMD.redcon=3` (`wake`, meaning request the wakeup state)
- `DCMD.redcon=4` (`sleep`, meaning request the sleep state)
- `get-thing-shadow` (`print`)

Default recipe values:
- thing name: `txing`
- region: `eu-central-1`
- endpoint file: `<repo>/certs/iot-data-ats.endpoint`

Override example:

```bash
just rig::wake thing_name=my-thing region=eu-central-1 endpoint_file=certs/iot-data-ats.endpoint
```

`print` prints the current real AWS Thing Shadow document.

`aws::shadow-reset` is the hard reset path for manual whole-device power cuts. It deletes the current txing shadow and reseeds it to the repository's clean offline baseline: `desired.redcon=null`, internal `desired.board.power=null`, `reported.redcon=4`, `reported.mcu.power=false`, `reported.mcu.ble.online=false`, `reported.board.power=false`, and `reported.board.wifi.online=false`.

## Runtime behavior

- Terminology:
  - `power=true` means the MCU is in the wakeup state.
  - `power=false` means the MCU is in the sleep state with periodic `5 s` rendezvous wakeups and short low-duty-cycle advertising windows.
- Operates in event-driven mode from MQTT subscriptions (no fixed-interval cloud polling).
- Subscribes to:
  - `$aws/things/<thing>/shadow/get/accepted`
  - `$aws/things/<thing>/shadow/update/accepted`
  - `spBv1.0/<group>/DCMD/<edge>/<thing>`
- On startup, requests full shadow with `$aws/things/<thing>/shadow/get`.
- On startup, also reflects static `reported.redcon=1` into the `rig` and `town` shadows and publishes `NBIRTH` for `rig`.
- Loads BLE UUIDs from `state.reported.mcu.ble.*` and validates them against the peripheral during short rendezvous sessions.
- Uses optional `state.reported.mcu.ble.deviceId` as the primary scan match for fast reconnect.
- Keeps a scanner running while disconnected and treats disconnects as normal behavior.
- While the MCU is in the sleep state, stays disconnected by default, watches the periodic advertisements to maintain BLE presence, and reconnects during a rendezvous window only when a BLE session is needed.
- While the MCU is in the wakeup state, maintains a live BLE session when possible.
- Uses one canonical 3-byte MCU State Report (`sleep flag` + `batteryMv`) from both BLE paths:
  - advertising manufacturer data while disconnected
  - GATT reads/notifications while connected
- Reflects each unresolved valid Sparkplug lifecycle command into `state.desired.redcon`.
- Publishes BLE connection state at `state.reported.mcu.ble.online`:
  - `true` only after sustained BLE presence has been confirmed
  - remains `true` while the device is connected or keeps advertising within the presence timeout
  - becomes `false` only after the configured presence timeout expires without a matching connection or advertisement
- Publishes Sparkplug lifecycle state:
  - `NBIRTH`/`NDATA` for node metric `rig.redcon=1`
  - `DBIRTH` when BLE reachability becomes online
  - `DDATA` when txing `redcon` or `batteryMv` changes while the device is born
  - `DDEATH` when BLE reachability times out
- If UUIDs are missing/invalid or do not match GATT, enters BLE UUID search mode and discovers UUIDs from service/characteristic properties.
- Ignores deprecated `state.desired.mcu.power` for lifecycle control.
- For `desired.redcon=1..3`, waits for the next advertisement if disconnected, connects if needed, writes the wakeup-state command only when `reported.mcu.power=false`, and clears `desired.redcon` after `reported.redcon` reaches the requested minimum readiness.
- For `desired.redcon=4`, first writes internal `desired.board.power=false` if the board is still up, waits for board-offline confirmation, then writes the BLE sleep command and clears `desired.redcon` after convergence.
- Updates top-level `state.reported.batteryMv` only when the observed MCU battery value changes, so the AWS shadow metadata timestamp for `batteryMv` tracks real battery changes instead of unrelated BLE state publishes.
- Publishes reported updates to AWS:
  - `state.reported.redcon`
  - `state.reported.batteryMv`
  - `state.reported.mcu.power`
  - `state.reported.mcu.ble.serviceUuid`
  - `state.reported.mcu.ble.sleepCommandUuid`
  - `state.reported.mcu.ble.stateReportUuid`
  - `state.reported.mcu.ble.online`
  - `state.reported.mcu.ble.deviceId` (when known)
- Clears `state.desired.redcon` when REDCON convergence completes.
- Clears internal `state.desired.board.power` after clean board shutdown and also on `DDEATH`.
- Mirrors current local state into `/tmp/txing_shadow.json`.
- Enforces single instance lock at `/tmp/rig.lock` (override with `--lock-file`).

## Useful options

```bash
./.venv/bin/rig --help
```

Common overrides:
- `--thing-name txing`
- `--rig-thing-name rig`
- `--town-thing-name town`
- `--sparkplug-group-id town`
- `--sparkplug-edge-node-id rig`
- `--scan-timeout 12`
- `--connect-timeout 5`
- `--board-offline-timeout 45`
- `--command-ack-timeout 1`
- `--command-ack-poll-interval 0.1`
- `--device-stale-after 0.75`
- `--scan-mode active`
- `--iot-endpoint <host>`
- `--iot-endpoint-file ../certs/iot-data-ats.endpoint`
- `--cert-file ../certs/txing.cert.pem`
- `--key-file ../certs/txing.private.key`
- `--ca-file ../certs/AmazonRootCA1.pem`
- `--client-id rig-pi5`
- `--debug` (verbose stdout logging)
- `--cloudwatch-log-group /town/rig/txing`
- `--cloudwatch-log-stream <stream-name>`
- `--cloudwatch-region <aws-region>` (override region; default inferred from IoT endpoint)
- `--no-cloudwatch-logs`
