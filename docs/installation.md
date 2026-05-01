# Installation

This guide covers host setup. AWS bring-up and teardown live in [aws.md](./aws.md). Day-to-day development commands live in [development.md](./development.md).

## Shared Assumptions

- The repository checkout is local to each host.
- Project-local AWS config stays under `config/`.
- `config/aws.env` is shared across the repo.
- `config/rig.env` is for the rig host.
- `config/board.env` is for the device board host.
- `config/aws.credentials` holds the source `town` credentials.
- `config/aws.config` holds the `rig` and `device` role assumptions.

Initialize the local config files on the machine where you are setting up a runtime:

```bash
cp config/aws.env.example config/aws.env
cp config/aws.credentials.example config/aws.credentials
cp config/aws.config.example config/aws.config
cp config/rig.env.example config/rig.env
cp config/board.env.example config/board.env
```

Only keep the host-specific env file that the machine actually needs.

## Rig Host

The rig is the always-on Raspberry Pi coordinator that owns Sparkplug publication, BLE wake/sleep control, and the `mcu` / `mcp` named-shadow updates.

### 1. Install OS Packages

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
  git curl jq awscli bluez just ca-certificates python3-venv \
  build-essential pkg-config cmake libssl-dev libcurl4-openssl-dev \
  uuid-dev libzip-dev libsqlite3-dev libyaml-dev libsystemd-dev \
  libevent-dev liburiparser-dev cgroup-tools
sudo systemctl enable --now bluetooth
```

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.profile
source ~/.profile
uv --version
```

### 2. Clone The Repo

```bash
export TXING_HOME="$HOME/txing"
git clone <repo-url> "$TXING_HOME"
cd "$TXING_HOME"
```

### 3. Configure AWS And Rig Identity

Edit:

- `config/aws.env`
  - `AWS_REGION`
  - `AWS_STACK_NAME`
  - `AWS_COGNITO_DOMAIN_PREFIX`
  - `AWS_ADMIN_EMAIL`
- `config/rig.env`
  - `SPARKPLUG_GROUP_ID`
  - `RIG_NAME`
  - optional `CLOUDWATCH_LOG_GROUP`
- `config/aws.config`
  - `[profile rig].role_arn = <RigRuntimeRoleArn>`
- `config/aws.credentials`
  - fill the `[town]` access keys

Validate access:

```bash
cd "$TXING_HOME"
just rig::check
```

### 4. Prepare Greengrass Lite Configuration

Production rig supervision is AWS IoT Greengrass Nucleus Lite, not a custom
`rig.service` Python systemd unit. The rig build clones Greengrass Lite from
upstream `main`, compiles it locally, installs its standard systemd units, and
starts the default `greengrass-lite.target`.

Before installing the service, the rig host must have:

- the shared stack deployed and `just aws::configure-indexing` applied
- the rig thing registered in AWS IoT
- a Greengrass core certificate, private key, and Amazon Root CA copied under
  `/var/lib/greengrass/credentials`
- the certificate attached to the rig thing and to the stack-created IoT policy
- `/etc/greengrass/config.yaml` configured for that rig thing

Resolve the endpoints and role alias from the town account:

```bash
cd "$TXING_HOME"
just aws-town iot describe-endpoint --endpoint-type iot:Data-ATS
just aws-town iot describe-endpoint --endpoint-type iot:CredentialProvider
just aws-town cloudformation describe-stacks \
  --stack-name <shared-stack-name> \
  --query "Stacks[0].Outputs[?OutputKey=='GreengrassTokenExchangeRoleAlias'].OutputValue | [0]" \
  --output text
```

Use those values in `/etc/greengrass/config.yaml`:

```yaml
system:
  privateKeyPath: "/var/lib/greengrass/credentials/rig.private.key"
  certificateFilePath: "/var/lib/greengrass/credentials/rig.cert.pem"
  rootCaPath: "/var/lib/greengrass/credentials/AmazonRootCA1.pem"
  rootPath: "/var/lib/greengrass"
  thingName: "rig"
services:
  aws.greengrass.NucleusLite:
    componentType: "NUCLEUS"
    configuration:
      awsRegion: "eu-central-1"
      iotCredEndpoint: "<credential-provider-endpoint>"
      iotDataEndpoint: "<data-ats-endpoint>"
      iotRoleAlias: "<GreengrassTokenExchangeRoleAlias>"
      runWithDefault:
        posixUser: "gg_component:gg_component"
      greengrassDataPlanePort: "8443"
      platformOverride: {}
```

Replace `thingName`, `awsRegion`, endpoints, role alias, and credential paths
with the actual rig values.

### 5. Build And Install The Greengrass Service

The rig Python runtime requires Python `3.12+`; Raspberry Pi OS Trixie satisfies
that requirement.

```bash
cd "$TXING_HOME"
just rig::build-native
just rig::build
just rig::install-service
```

`just rig::install-service` removes the legacy `rig.service` if present and
installs and starts the standard Greengrass Lite systemd units from the native
build. It creates the default `ggcore` and `gg_component` users if they are
missing, keeps `/var/lib/greengrass` owned by `ggcore:ggcore`, and starts
`greengrass-lite.target` through the upstream `misc/run_nucleus` script.

Inspect Greengrass service health with:

```bash
sudo systemctl status --with-dependencies greengrass-lite.target
sudo journalctl -a -f
```

Deploy `dev.txing.rig.SparkplugManager` and `dev.txing.rig.ConnectivityBle` as
Greengrass components. The recipe templates live in `rig/greengrass/recipes`.

Useful foreground commands:

```bash
cd "$TXING_HOME"
just rig::run
just rig::debug
just rig::wake
just rig::sleep
```

## Board Host

The board is the device-side Raspberry Pi. It publishes the `board` and `video` named shadows, runs the KVS sender, and exposes board MCP.

This guide assumes:

- Raspberry Pi OS Lite 64-bit
- Network is managed by `NetworkManager`
- the board remains headless
- AWS resources and the target device thing already exist

If your image is still using a different network manager, switch it before enabling the read-only layout below.

Keep the board root filesystem writable until the runtime, native sender, and service unit are installed.

### 1. Flash And Boot

- Flash Raspberry Pi OS Lite 64-bit.
- Enable SSH and configure Wi-Fi during imaging if needed.
- Boot once with the default writable root filesystem.

### 2. Install OS Packages

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
  git curl jq awscli just cmake pkg-config build-essential \
  libssl-dev libcurl4-openssl-dev liblog4cplus-dev libsrtp2-dev \
  libusrsctp-dev libwebsockets-dev zlib1g-dev libcamera-dev \
  ca-certificates python3-lgpio network-manager
```

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.profile
source ~/.profile
uv --version
```

### 3. Clone The Repo And Copy Config

```bash
export TXING_HOME="$HOME/txing"
git clone <repo-url> "$TXING_HOME"
cd "$TXING_HOME"
```

Populate:

- `config/aws.env`
- `config/aws.credentials`
- `config/aws.config`
- `config/board.env`

Board-specific values to set in `config/board.env`:

- `THING_NAME`
- `BOARD_VIDEO_REGION`
- `BOARD_VIDEO_SENDER_COMMAND`
- `KVS_DUALSTACK_ENDPOINTS=ON`
- `BOARD_DRIVE_CMD_RAW_MIN_SPEED`
- `BOARD_DRIVE_CMD_RAW_MAX_SPEED`

If you are using the current default chassis, the measured bring-up values are:

```bash
BOARD_DRIVE_CMD_RAW_MIN_SPEED=50
BOARD_DRIVE_CMD_RAW_MAX_SPEED=250
```

In `config/aws.config`, set `[profile device].role_arn = <DeviceRuntimeRoleArn>`.

### 4. Enable PWM Overlay

Append this to `/boot/firmware/config.txt` while `/boot/firmware` is writable:

```ini
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

### 5. Build The Native Sender And Python Runtime

Build the repo-owned KVS sender:

```bash
cd "$TXING_HOME"
just board::build-native
```

Point `BOARD_VIDEO_SENDER_COMMAND` at the built binary, typically:

```bash
export BOARD_VIDEO_SENDER_COMMAND="$TXING_HOME/devices/unit/board/kvs_master/build/txing-board-kvs-master"
```

Build the Python runtime:

```bash
cd "$TXING_HOME"
python3 --version
just board::build
```

Validate the board runtime AWS access:

```bash
cd "$TXING_HOME"
just board::check
```

### 6. Smoke Test And Install The Service

Run one foreground publish as `root`:

```bash
cd "$TXING_HOME/devices/unit/board"
sudo ./.venv/bin/board \
  --once \
  --video-region <aws-region> \
  --video-sender-command "$BOARD_VIDEO_SENDER_COMMAND"
```

Replace `<aws-region>` with the same value you configured as `BOARD_VIDEO_REGION` in `config/board.env`.

Then install the service:

```bash
cd "$TXING_HOME"
just board::install-service "$BOARD_VIDEO_SENDER_COMMAND"
sudo systemctl status board
sudo journalctl -u board -f
```

The generated unit:

- runs `board` as `root`
- loads `config/aws.env` and optional `config/board.env`
- enables `NetworkManager-wait-online.service`
- waits for clock synchronization before starting the AWS-backed video sender

### 7. Configure The Read-Only Root Filesystem

The current board runtime is compatible with a read-only root as long as these writable paths stay on tmpfs:

- `/tmp`
  - board shadow mirror: `/tmp/txing_board_shadow.json`
  - board video sender state: `/tmp/txing_board_video_state.json`
  - MCP WebRTC socket: `/tmp/txing_board_mcp_webrtc.sock`
- `/var/tmp`
- `/var/log`
- `/var/lib/NetworkManager`

The native sender keeps the KVS signaling cache in memory only. It does not depend on the SDK's default `.SignalingCache_v1` file.

Replace the `PARTUUID` placeholders with the target board values from `lsblk -o NAME,PARTUUID,MOUNTPOINT`.

Use this `fstab` layout:

```fstab
proc            /proc           proc    defaults          0       0
PARTUUID=<boot-partuuid>  /boot/firmware  vfat    defaults,ro,noatime         0       2
PARTUUID=<root-partuuid>  /               ext4    defaults,ro,noatime         0       1
tmpfs                     /tmp                 tmpfs nosuid,nodev,mode=1777,size=32M 0 0
tmpfs                     /var/tmp             tmpfs nosuid,nodev,mode=1777,size=16M 0 0
tmpfs                     /var/log             tmpfs nosuid,nodev,mode=0755,size=16M 0 0
tmpfs                     /var/lib/NetworkManager tmpfs nosuid,nodev,mode=0755,size=16M 0 0
```

Useful aliases:

```bash
alias root-ro='sudo bash -c "rm -rf /var/tmp/* /tmp/* ; sync ; mount -o remount,ro /boot/firmware ; mount -o remount,ro /"'
alias root-rw='sudo bash -c "mount -o remount,rw /; mount -o remount,rw /boot/firmware; umount /var/tmp /tmp; sudo systemctl daemon-reload"'
```

Operational notes:

- Do all package installs, repo updates, rebuilds, and `systemd` unit changes while the root is writable.
- Switch back to read-only only after the runtime, native sender, and config files are in place.
- If you need to change board code, env files, `/boot/firmware/config.txt`, or the systemd unit later, use `root-rw`, make the change, restart the affected service, then `root-ro`.

### 8. Final Verification

Reboot once after enabling the read-only layout:

```bash
sudo reboot
```

After reconnecting:

```bash
sudo systemctl status board
sudo journalctl -u board -f
```

Useful board commands:

```bash
cd "$TXING_HOME"
just board::run
just board::once
just board::motor-raw 240 240
just board::motor-stop
```
