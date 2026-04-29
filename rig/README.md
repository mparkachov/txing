# `rig` lifecycle subproject

Python service for the Raspberry Pi 5 rig runtime.

Responsibilities:
- Connect directly to AWS IoT Core over SigV4-authenticated MQTT over WebSockets
- Act as the `rig` lifecycle runtime in the same process
- Synchronize named Thing Shadows for all registered devices assigned to this rig
- Accept Sparkplug `DCMD.redcon` lifecycle commands and publish `NBIRTH`/`NDEATH`/`DBIRTH`/`DDATA`/`DDEATH`
- Bridge REDCON-driven wakeup-state and sleep-state changes to the MCU over BLE rendezvous sessions
- Publish MCU state to the `mcu` named shadow
- Publish shared battery state to the `device` named shadow
- Publish derived readiness to `sparkplug.state.reported.redcon`
- Load assigned devices from the dynamic AWS IoT thing group named by `RIG_NAME`
- Persist last known BLE reconnect hints to AWS IoT thing attribute `bleDeviceId`

Shadow contract source of truth:
- `../devices/unit/aws/*-shadow.schema.json`
- `../devices/unit/docs/device-rig-shadow-spec.md`
- Design decision: `rig` owns and evolves the `mcu.*` shadow subtree contract.

High-level architecture:
- Sparkplug host -> AWS IoT MQTT -> rig -> BLE -> mcu
- rig -> AWS IoT Thing Shadow (`device_id`)

## Requirements

The system requires these tools installed:
- `uv`
- `just`
- `jq`
- `aws` (AWS CLI)

The documented repo workflow keeps AWS settings inside the checkout under `../config/`.
`just` recipes load `../config/aws.env` first and then optional `../config/rig.env` before invoking AWS CLI or `rig`.
Use `just aws-rig ...` for AWS CLI commands with the rig/runtime profile and `just aws-town ...` for AWS CLI commands with the town account profile.
The recommended field setup is: the `town` profile in `../config/aws.credentials` holds access keys for the AWS account that owns the resources, and the `rig` profile in `../config/aws.config` assumes the stack output role `RigRuntimeRoleArn`.
Put rig-specific runtime defaults in `../config/rig.env`: `RIG_NAME`, `SPARKPLUG_GROUP_ID`, and `CLOUDWATCH_LOG_GROUP`. The Sparkplug edge node id is derived from `RIG_NAME`.
When rig starts under `systemd`, it loads `../config/aws.env` first and then optional `../config/rig.env`, while still falling back from `AWS_RIG_PROFILE` to the standard `AWS_PROFILE` env used by the AWS SDK chain.

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
- set the shared AWS/profile defaults in `config/aws.env`
- set the rig runtime defaults in `config/rig.env`

```bash
cd ~/txing
mkdir -p config
cp config/aws.env.example config/aws.env
cp config/rig.env.example config/rig.env
cp config/aws.credentials.example config/aws.credentials
cp config/aws.config.example config/aws.config
$EDITOR config/aws.env
$EDITOR config/rig.env
$EDITOR config/aws.credentials
$EDITOR config/aws.config

just aws-rig sts get-caller-identity
```

Adjust these values explicitly:

- `config/aws.env`
  - `AWS_REGION`
  - `AWS_STACK_NAME`
  - `AWS_COGNITO_DOMAIN_PREFIX`
  - `AWS_ADMIN_EMAIL`
  - `AWS_TOWN_PROFILE`, `AWS_RIG_PROFILE`, `AWS_DEVICE_PROFILE` only if you do not want the default local profile names
  - `AWS_SHARED_CREDENTIALS_FILE` and `AWS_CONFIG_FILE` only if the files are not kept under `config/`
- `config/rig.env`
  - `SPARKPLUG_GROUP_ID`: town slug
  - `RIG_NAME`: rig slug
  - `CLOUDWATCH_LOG_GROUP` only if you want a non-default log group
- `config/aws.config`
  - set `[profile rig].role_arn` to the deployed `RigRuntimeRoleArn`
- `config/aws.credentials`
  - fill the `[town]` account access keys

5. Validate AWS access and rig runtime configuration:

```bash
cd ~/txing
just rig::check
```

This check validates required local tools plus caller identity, IoT control-plane access including Data-ATS endpoint discovery, and CloudWatch log writes.

6. `just aws::bootstrap` is obsolete for `rig` certificate provisioning.
`rig` no longer uses AWS IoT thing certificates. The recipe may still exist for other legacy flows in the repo, but it is not part of the rig runtime setup anymore.

7. Build the rig runtime with the OS `python3` and verify startup:

```bash
cd ~/txing/rig
python3 --version
just build
./.venv/bin/rig --help
just debug
```

`build` is the normal install step for the rig runtime. It creates or updates `rig/.venv/` from the OS `python3` on `PATH` and installs the packaged entry points there. You do not need to run `sync` first. `rig` requires Python `3.12+`, so make sure `python3 --version` on the host machine satisfies that before running `just build`.

8. Optional: install the `systemd` service:

```bash
cd ~/txing
just rig::install-service
sudo journalctl -u rig -f
```

The `just rig::install-service` task enables `bluetooth`, writes `/etc/systemd/system/rig.service` for the current user and checkout path, reloads `systemd`, and enables `rig`.
It points `ExecStart` at the built rig executable in `rig/.venv/bin/rig`, sets `WorkingDirectory` to the repo root, and loads `config/aws.env` plus optional `config/rig.env` through `EnvironmentFile=`. That means shared AWS values such as `AWS_REGION`, `AWS_RIG_PROFILE`, `AWS_SHARED_CREDENTIALS_FILE`, and `AWS_CONFIG_FILE` come from `config/aws.env`, while rig runtime values such as `RIG_NAME`, `SPARKPLUG_GROUP_ID`, and `CLOUDWATCH_LOG_GROUP` come from `config/rig.env` by default. Optional recipe overrides are positional in the order shown by `just --summary` or `just --show rig::install-service`; prefer editing the env files for persistent service configuration. The rig runtime derives the Sparkplug edge node id from the resolved `RIG_NAME` and ignores any separate stale override. The rig runtime discovers the AWS IoT Data-ATS endpoint automatically from the configured AWS region/profile.

## Run rig

Run from `rig/`:

```bash
just run
```

By default this reads `../config/aws.env` first and then optional `../config/rig.env`, exports the project-local AWS credential/config file paths from there, and autodiscovers the AWS IoT Data-ATS endpoint from the configured AWS region/profile:
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

Use `just` recipes to publish Sparkplug lifecycle commands.

From repository root:

```bash
just rig::wake
just rig::sleep
just rig::print
just aws::shadow <thing>
just aws::shadow-reset <thing>
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

`print` prints the current real AWS Thing Shadow document.

`aws::shadow-reset <thing>` is the hard reset path for manual whole-device power cuts on unit things. It deletes the classic unnamed shadow and reseeds the unit named shadows to the repository's clean offline baseline: `sparkplug reported.redcon=4`, `device reported.batteryMv=3750`, `mcu reported.power=false`, `mcu reported.online=false`, `board reported.power=false`, and `board reported.wifi.online=false`.

For rig and town things, `aws::shadow` and `aws::shadow-reset` use only the `sparkplug` named shadow; a full reset also removes known unit-only named shadows if they were created by an older recipe. Use `aws::shadow-reset <thing> <shadow>` to reset one valid named shadow for that thing type.

Use the registry helpers with positional arguments to create/update rig membership and inspect current membership:

```bash
just aws::configure-indexing
just aws::register-town town
just aws::register-rig town rig
just aws::register-device town rig unit
just aws::assign-device unit-01 town rig
just aws::things-for-rig rig
```

Provision in that order on a fresh AWS environment:

- `aws::deploy` creates the stack-owned AWS resources and the `town` / `rig` thing types.
- `aws::configure-indexing` enables the searchable/indexed registry fields used by the hierarchy:
  - `attributes.name`
  - `attributes.town`
  - `attributes.rig`
- `attributes.shortId` and `attributes.bleDeviceId` stay in the IoT registry as metadata only.
- `aws::register-town`, `aws::register-rig`, and `aws::register-device` then create the actual registry objects and shadows.

For a destructive rebuild:

- delete all registered things (`town-*`, `rig-*`, and device things such as `unit-*`)
- delete the dynamic town and rig thing groups
- deprecate all thing types, including stack-owned `town` / `rig` and any device type such as `unit`
- wait 5 minutes after thing-type deprecation
- empty the web app S3 bucket
- then delete the stack

The longer stack bootstrap and deletion flow is documented in `web/README.md`.

## Runtime behavior

- Terminology:
  - `power=true` means the MCU is in the wakeup state.
  - `power=false` means the MCU is in the sleep state with periodic `5 s` rendezvous wakeups and short low-duty-cycle advertising windows.
- Operates in event-driven mode from MQTT subscriptions (no fixed-interval cloud polling).
- On startup, lists txings from the dynamic AWS IoT thing group named by `RIG_NAME`, then `DescribeThing`s each txing to read `attributes.rig` and `attributes.bleDeviceId`.
- Subscribes to each managed txing:
  - `$aws/things/<thing>/shadow/name/<shadow>/get/accepted`
  - `$aws/things/<thing>/shadow/name/<shadow>/update/accepted`
  - `txings/<thing>/mcp/descriptor`
  - `txings/<thing>/mcp/status`
  - `spBv1.0/<group>/DCMD/<edge>/<thing>`
- On startup, requests the `sparkplug`, `device`, `mcu`, and `board` named shadows for each managed txing.
- Mirrors retained MCP descriptor/status facts into Sparkplug `services/mcp/*` device metrics while keeping rig as the only Sparkplug publisher for the selected device session.
- Publishes `NBIRTH` for the Sparkplug node `rig` and writes the corresponding rig thing shadow `sparkplug reported.redcon=1` directly from the rig runtime.
- Publishes `NDEATH` on shutdown and best-effort writes the rig thing shadow `sparkplug reported.redcon=4` directly from the rig runtime.
- Starts from the built-in BLE UUID configuration and validates it against the peripheral during short rendezvous sessions.
- Uses AWS IoT thing attribute `bleDeviceId` as the primary persisted fast-reconnect hint.
- Keeps a scanner running while disconnected and treats disconnects as normal behavior.
- Shares one BLE scanner across all txings assigned to the rig and allows one active BLE session at a time.
- While the MCU is in the sleep state, stays disconnected by default, watches the periodic advertisements to maintain BLE presence, and reconnects during a rendezvous window only when a BLE session is needed.
- While the MCU is in the wakeup state, maintains a live BLE session when possible.
- Uses one canonical 3-byte MCU State Report (`sleep flag` + `batteryMv`) from both BLE paths:
  - advertising manufacturer data while disconnected
  - GATT reads/notifications while connected
- Tracks unresolved Sparkplug lifecycle commands in memory only; device shadows are reported-only.
- Publishes BLE connection state at `state.mcu reported.online`:
  - `true` only after sustained BLE presence has been confirmed
  - remains `true` while the device is connected or keeps advertising within the presence timeout
  - becomes `false` only after the configured presence timeout expires without a matching connection or advertisement
- Publishes Sparkplug lifecycle state:
  - `NBIRTH`/`NDATA` for node metric `rig.redcon=1`
  - `DBIRTH` when BLE reachability becomes online
  - `DDATA` when either txing Sparkplug report field changes while the device is born: `redcon` or `batteryMv`
  - `DDEATH` when BLE reachability times out
- If UUIDs are missing/invalid or do not match GATT, enters BLE UUID search mode and discovers UUIDs from service/characteristic properties.
- Ignores deprecated shadow metadata fields `state.reported.bleDeviceId` and `state.reported.homeRig`.
- For `DCMD.redcon=1..3`, waits for the next advertisement if disconnected, connects if needed, writes the wakeup-state command only when `mcu reported.power=false`, and clears the in-memory target after `sparkplug reported.redcon` reaches the requested minimum readiness.
- For `DCMD.redcon=4`, waits for `reported.power=false`, then writes the BLE sleep command and clears the in-memory target after convergence.
- Updates `state.device reported.batteryMv` only when the observed MCU battery value changes, so the AWS shadow metadata timestamp for `batteryMv` tracks real battery changes instead of unrelated BLE state publishes.
- After a successful BLE association, writes the observed BLE address back to AWS IoT thing attribute `bleDeviceId` if it changed.
- Publishes reported updates to AWS:
  - `sparkplug.state.reported.redcon`
  - `state.device reported.batteryMv`
  - `state.mcu reported.power`
  - `state.mcu reported.online`
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
- `--client-id rig-pi5`
- `--debug` (verbose stdout logging)
- `--cloudwatch-log-group /town/rig/txing`
- `--cloudwatch-log-stream <stream-name>`
- `--cloudwatch-region <aws-region>` (override region; default: same as AWS region)
- `--no-cloudwatch-logs`

Authentication selection uses the standard AWS SDK environment, not rig-specific CLI flags:
- `AWS_PROFILE`
- `AWS_REGION`
- `AWS_SHARED_CREDENTIALS_FILE`
- `AWS_CONFIG_FILE`

Rig runtime selection is normally loaded from `config/rig.env`:
- `RIG_NAME`
- `SPARKPLUG_GROUP_ID`
- `CLOUDWATCH_LOG_GROUP`

When the shared AWS config from `config/aws.env` is loaded, rig also accepts `AWS_RIG_PROFILE` as the repo-local profile selector and maps it onto `AWS_PROFILE` before constructing the AWS SDK session.
