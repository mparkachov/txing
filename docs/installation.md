# Installation

This guide covers host setup. AWS bring-up and teardown live in [aws.md](./aws.md). Day-to-day development commands live in [development.md](./development.md).

## Shared Assumptions

- The repository checkout is local to each host.
- Project-local AWS config stays under `config/`.
- `config/aws.env` is the single non-secret AWS/runtime config file.
- `config/aws.credentials` holds the source `town` credentials.

Initialize the local config files on the machine where you are setting up a runtime:

```bash
cp config/aws.env.example config/aws.env
cp config/aws.credentials.example config/aws.credentials
```

## Rig Host

The rig is the always-on Raspberry Pi coordinator that owns Sparkplug publication, BLE wake/sleep control, and the `mcu` / `mcp` named-shadow updates.

### 1. Install OS Packages

`just rig::build-native` compiles Greengrass Lite locally. Install the native
build toolchain before running it; otherwise the first failure will be similar
to `cmake: command not found`.

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

Verify the required native tools are on `PATH`:

```bash
cmake --version
cc --version
pkg-config --version
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
  - `TXING_TOWN_NAME`
  - `TXING_RIG_NAME`
  - `TXING_DEVICE_NAME`
  - `TXING_DEVICE_TYPE`
  - `AWS_COGNITO_DOMAIN_PREFIX`
  - `AWS_ADMIN_EMAIL`
  - `SPARKPLUG_GROUP_ID`
  - `RIG_NAME`
  - optional `CLOUDWATCH_LOG_GROUP`
- `config/aws.credentials`
  - fill the `[town]` access keys

Validate access and the rig certificate path used by Greengrass:

```bash
cd "$TXING_HOME"
just rig::check
```

`just rig::check` does not inspect systemd or `/var/lib/greengrass`. It uses the
certificate material under `config/certs/rig/` to verify AWS IoT MQTT mTLS
connectivity and AWS IoT Credentials Provider role-alias access, matching the
certificate inputs later installed by `just rig::install-service`.

### 4. Prepare Greengrass Lite Configuration

Production rig supervision is AWS IoT Greengrass Nucleus Lite, not a custom
`rig.service` Python systemd unit. The rig build clones Greengrass Lite from
upstream `main`, compiles it locally, installs its standard systemd units, and
starts the default `greengrass-lite.target`.

Before installing the service, the rig host must have:

- the AWS stacks deployed with `just aws::deploy`, `just aws::town-deploy`, and `just aws::rig-deploy`
- the configured rig thing registered in AWS IoT by `just aws::rig-deploy`
- rig certificate material generated with `just aws::cert` under
  `config/certs/rig/`

Create the rig certificate material. The recipe resolves the configured rig
thing from AWS IoT registry indexing, attaches the stack IoT policy, and writes
the certificate, public key, private key, certificate ARN, and Amazon Root CA 1 under
`config/certs/rig/`. That directory is explicitly ignored by git.

```bash
cd "$TXING_HOME"
just aws::cert
```

`just rig::install-service` copies `config/certs/rig/rig.cert.pem` and
`config/certs/rig/rig.private.key` into
`/var/lib/greengrass/credentials`, downloads Amazon Root CA 1 into that same
directory, creates `ggcore`/`gg_component` if needed, and changes
`/var/lib/greengrass` ownership to `ggcore:ggcore`. It also generates
`/etc/greengrass/config.yaml` automatically by resolving the configured rig
thing through AWS IoT registry indexing, resolving the AWS IoT data and
credential-provider endpoints, and reading the
`GreengrassTokenExchangeRoleAlias` output from the rig stack.

### 5. Build And Install The Greengrass Service

The rig Python runtime requires Python `3.12+`; Raspberry Pi OS Trixie satisfies
that requirement.

```bash
cd "$TXING_HOME"
just rig::build-native
just rig::build
just rig::install-service
just rig::deploy
```

`just rig::install-service` installs and starts the standard Greengrass Lite
systemd units from the native build. It does not manage the old custom
`rig.service`; remove that unit manually before using the Greengrass structure
if it still exists on an older host. The recipe creates the default `ggcore` and
`gg_component` users if they are missing, keeps `/var/lib/greengrass` owned by
`ggcore:ggcore`, and starts `greengrass-lite.target` through the upstream
`misc/run_nucleus` script.

`just rig::deploy` packages the current rig Python source and dependencies into
a temporary local Greengrass artifact Python tree using `uv`, generates
Greengrass Lite-compatible recipes with the configured rig identity, and deploys
`dev.txing.rig.SparkplugManager` plus `dev.txing.rig.ConnectivityBle` with
`ggl-cli deploy`. It depends on `just rig::build`, so after changing rig code or
pulling new code, run `just rig::deploy`. A Greengrass service restart alone
restarts the previously deployed component artifact.

Inspect Greengrass service health with:

```bash
sudo systemctl status --with-dependencies greengrass-lite.target
sudo journalctl -a -f
sudo journalctl -a -f -u ggl.dev.txing.rig.SparkplugManager.service -u ggl.dev.txing.rig.ConnectivityBle.service
```

Restart the installed Bluetooth and Greengrass Lite systemd units without
deploying a new component artifact with:

```bash
just rig::restart
```

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

Board-specific values to set in `config/aws.env`:

- `TXING_DEVICE_NAME`
- `TXING_DEVICE_TYPE`
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

Replace `<aws-region>` with the same value you configured as `BOARD_VIDEO_REGION` in `config/aws.env`.

Then install the service:

```bash
cd "$TXING_HOME"
just board::install-service "$BOARD_VIDEO_SENDER_COMMAND"
sudo systemctl status board
sudo journalctl -u board -f
```

The generated unit:

- runs `board` as `root`
- loads `config/aws.env`
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
