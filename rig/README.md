# `rig` lifecycle subproject

Python service for the Raspberry Pi 5 rig runtime.

Responsibilities:
- Connect directly to AWS IoT Core over SigV4-authenticated MQTT over WebSockets
- Act as the phase-1 `rig` lifecycle runtime in the same process
- Synchronize classic Thing Shadows for all txings assigned to this rig
- Accept Sparkplug `DCMD.redcon` lifecycle commands and publish `NBIRTH`/`NDATA`/`DBIRTH`/`DDATA`/`DDEATH`
- Bridge REDCON-driven wakeup-state and sleep-state changes to the MCU over BLE rendezvous sessions
- Publish MCU state to `state.reported.mcu.*`
- Publish derived readiness at top-level `state.reported.redcon`
- Load assigned txings from the dynamic AWS IoT thing group named by `RIG_NAME`
- Persist last known BLE reconnect hints to AWS IoT thing attribute `bleDeviceId`

Shadow contract source of truth:
- `../docs/txing-shadow.schema.json`
- `../docs/device-rig-shadow-spec.md`
- Design decision: `rig` owns and evolves the `mcu.*` shadow subtree contract.

High-level architecture:
- Sparkplug host -> AWS IoT MQTT -> rig -> BLE -> mcu
- rig -> AWS IoT Thing Shadow (`txing`)

## Requirements

The system requires these tools installed:
- `uv`
- `just`
- `jq`
- `aws` (AWS CLI)

The documented repo workflow keeps AWS settings inside the checkout under `../config/`.
`just` recipes load `../config/aws.env` automatically and export project-local `AWS_SHARED_CREDENTIALS_FILE`, `AWS_CONFIG_FILE`, `AWS_REGION`, and `AWS_PROFILE` from that file before invoking AWS CLI or `rig`.
Use `just aws-rig ...` for AWS CLI commands with the rig/runtime profile and `just aws-town ...` for AWS CLI commands with the town account profile.
The recommended field setup is: the `town` profile in `../config/aws.credentials` holds access keys for the AWS account that owns the resources, and the `rig` profile in `../config/aws.config` assumes the stack output role `RigRuntimeRoleArn`.

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

4. Copy the project-local AWS config examples and fill them in.
For an already provisioned town account, the minimum rig setup is:
- put the town account access key in `config/aws.credentials`
- set the runtime role ARN in `config/aws.config`
- set the profile names and defaults in `config/aws.env`

```bash
cd ~/txing
mkdir -p config
cp config/aws.env.example config/aws.env
cp config/aws.credentials.example config/aws.credentials
cp config/aws.config.example config/aws.config
$EDITOR config/aws.env
$EDITOR config/aws.credentials
$EDITOR config/aws.config

just aws-rig sts get-caller-identity
```

5. Write the AWS IoT endpoint file used by `rig`:

```bash
cd ~/txing
just aws::endpoint
```

6. Validate AWS access and endpoint configuration:

```bash
cd ~/txing
just rig::check
```

This check validates required local tools plus caller identity, IoT control-plane access, CloudWatch log writes, and the configured Data-ATS endpoint file.

7. `just aws::bootstrap` is obsolete for `rig` certificate provisioning.
`rig` no longer uses AWS IoT thing certificates. The recipe may still exist for other legacy flows in the repo, but it is not part of the rig runtime setup anymore.

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
It points `ExecStart` at the built rig executable in `rig/.venv/bin/rig` and writes the runtime contract into `Environment=` lines for `RIG_NAME`, `SPARKPLUG_GROUP_ID`, `SPARKPLUG_EDGE_NODE_ID`, `IOT_ENDPOINT_FILE`, `CLOUDWATCH_LOG_GROUP`, `AWS_REGION`, and optionally `AWS_PROFILE`, `AWS_SHARED_CREDENTIALS_FILE`, and `AWS_CONFIG_FILE`, so run `just rig::build` first.

## Run rig

Run from `rig/`:

```bash
just run
```

By default this reads `../config/aws.env`, exports the project-local AWS credential/config file paths from there, and uses the endpoint file:
- endpoint file: `../certs/iot-data-ats.endpoint`
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

Use the registry helpers to assign txings to a rig and inspect current membership:

```bash
just aws::upsert-rig-group rig
just aws::assign-rig txing-01 rig
just aws::things-for-rig rig
```

## Runtime behavior

- Terminology:
  - `power=true` means the MCU is in the wakeup state.
  - `power=false` means the MCU is in the sleep state with periodic `5 s` rendezvous wakeups and short low-duty-cycle advertising windows.
- Operates in event-driven mode from MQTT subscriptions (no fixed-interval cloud polling).
- On startup, lists txings from the dynamic AWS IoT thing group named by `RIG_NAME`, then `DescribeThing`s each txing to read `attributes.rig` and `attributes.bleDeviceId`.
- Subscribes to each managed txing:
  - `$aws/things/<thing>/shadow/get/accepted`
  - `$aws/things/<thing>/shadow/update/accepted`
  - `spBv1.0/<group>/DCMD/<edge>/<thing>`
- On startup, requests the full shadow for each managed txing with `$aws/things/<thing>/shadow/get`.
- Publishes `NBIRTH` for the Sparkplug node `rig`, but does not maintain AWS IoT shadows for `rig` or `town`.
- Loads BLE UUIDs from `state.reported.mcu.ble.*` and validates them against the peripheral during short rendezvous sessions.
- Uses AWS IoT thing attribute `bleDeviceId` as the primary persisted fast-reconnect hint.
- Keeps a scanner running while disconnected and treats disconnects as normal behavior.
- Shares one BLE scanner across all txings assigned to the rig and allows one active BLE session at a time.
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
  - `DDATA` when either txing Sparkplug report field changes while the device is born: `redcon` or `batteryMv`
  - `DDEATH` when BLE reachability times out
- If UUIDs are missing/invalid or do not match GATT, enters BLE UUID search mode and discovers UUIDs from service/characteristic properties.
- Ignores deprecated `state.desired.mcu.power` for lifecycle control.
- Ignores deprecated shadow metadata fields `state.reported.bleDeviceId`, `state.reported.homeRig`, and `state.reported.mcu.ble.deviceId`.
- For `desired.redcon=1..3`, waits for the next advertisement if disconnected, connects if needed, writes the wakeup-state command only when `reported.mcu.power=false`, and clears `desired.redcon` after `reported.redcon` reaches the requested minimum readiness.
- For `desired.redcon=4`, first writes internal `desired.board.power=false` if the board is still up, waits for board-offline confirmation, then writes the BLE sleep command and clears `desired.redcon` after convergence.
- Updates top-level `state.reported.batteryMv` only when the observed MCU battery value changes, so the AWS shadow metadata timestamp for `batteryMv` tracks real battery changes instead of unrelated BLE state publishes.
- After a successful BLE association, writes the observed BLE address back to AWS IoT thing attribute `bleDeviceId` if it changed.
- Publishes reported updates to AWS:
  - `state.reported.redcon`
  - `state.reported.batteryMv`
  - `state.reported.mcu.power`
  - `state.reported.mcu.ble.serviceUuid`
  - `state.reported.mcu.ble.sleepCommandUuid`
  - `state.reported.mcu.ble.stateReportUuid`
  - `state.reported.mcu.ble.online`
- Clears `state.desired.redcon` when REDCON convergence completes.
- Clears internal `state.desired.board.power` after clean board shutdown and also on `DDEATH`.
- Does not rely on local shadow cache files; startup state comes from AWS IoT shadow plus IoT thing attributes.
- Enforces single instance lock at `/tmp/rig.lock` (override with `--lock-file`).

## Useful options

```bash
./.venv/bin/rig --help
```

Common overrides:
- `--rig-name rig`
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
- `--client-id rig-pi5`
- `--debug` (verbose stdout logging)
- `--cloudwatch-log-group /town/rig/txing`
- `--cloudwatch-log-stream <stream-name>`
- `--cloudwatch-region <aws-region>` (override region; default inferred from IoT endpoint)
- `--no-cloudwatch-logs`

Authentication selection uses the standard AWS SDK environment, not rig-specific CLI flags:
- `AWS_PROFILE`
- `AWS_REGION`
- `AWS_SHARED_CREDENTIALS_FILE`
- `AWS_CONFIG_FILE`
