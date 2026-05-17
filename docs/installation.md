# Installation

This guide covers host setup. AWS bring-up and teardown live in [aws.md](./aws.md). Day-to-day development commands live in [development.md](./development.md).

## Shared Assumptions

- Development machines may use a repository checkout.
- Stable rig and board hosts install release artifacts with `mise` and do not
  need a source checkout for the stable runtime path.
- Project-local AWS config in a checkout stays under `config/`.
- Stable rig host AWS config lives under `/home/txing/.config/txing/rig/`.
- `aws.env` is the single non-secret AWS/runtime config file.
- `aws.credentials` holds the source `town` credentials.

Initialize the local config files on the machine where you are setting up a runtime:

```bash
cp config/aws.env.example config/aws.env
cp config/aws.credentials.example config/aws.credentials
```

## Rig Host

The rig is the always-on coordinator that owns Sparkplug publication. The
current `unit` rig type also owns BLE wake/sleep control and `ble`, `power`,
and `mcp` named-shadow updates.

### 1. Install OS Packages

Stable rig installs do not compile Greengrass Lite or txing rig components on
the host. Install OS runtime packages and operator tools only:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
  curl jq ca-certificates unzip \
  libssl3 libcurl4 libdbus-1-3 libzip4 libyaml-0-2 libsystemd0 \
  libevent-2.1-7 liburiparser1 cgroup-tools
```

Install AWS CLI v2 from AWS, not from the OS package repository:

```bash
case "$(uname -m)" in
  x86_64|amd64) aws_cli_arch="x86_64" ;;
  aarch64|arm64) aws_cli_arch="aarch64" ;;
  *) echo "Unsupported AWS CLI architecture: $(uname -m)" >&2; exit 1 ;;
esac
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${aws_cli_arch}.zip" -o /tmp/awscliv2.zip
rm -rf /tmp/aws
if ! command -v unzip >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y unzip
fi
unzip -q /tmp/awscliv2.zip -d /tmp
sudo /tmp/aws/install --update
rm -rf /tmp/aws /tmp/awscliv2.zip
aws --version
```

Create the runtime user if it does not already exist:

```bash
if ! id -u txing >/dev/null 2>&1; then
  sudo useradd -m -s /bin/bash txing
fi
sudo install -d -o txing -g txing -m 700 /home/txing/.config/txing/rig
```

For `RIG_TYPE=raspi`, install and enable Bluetooth manually before deploying the
unit connectivity component:

```bash
sudo apt install -y bluez
sudo systemctl enable --now bluetooth.service
```

Install `mise` for the `txing` user. The stable rig artifacts live in that
user's mise install tree:

```bash
sudo -u txing env HOME=/home/txing bash -lc '
  mkdir -p "$HOME/.local/bin"
  curl https://mise.run | sh
  if ! grep -qxF '\''eval "$($HOME/.local/bin/mise activate bash)"'\'' "$HOME/.bashrc"; then
    echo '\''eval "$($HOME/.local/bin/mise activate bash)"'\'' >> "$HOME/.bashrc"
  fi
'
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise --version
```

### 2. Install Rig Mise Tool Config

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/rig/install-mise-tools.sh | sudo bash
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise install
```

### 3. Configure AWS Access

Create and edit:

- `/home/txing/.config/txing/rig/aws.env`
  - `AWS_REGION`
  - `AWS_STACK_NAME`
  - optional `TXING_TOWN_ID`
  - optional `TXING_RIG_ID`
  - optional `CLOUDWATCH_LOG_GROUP`
- `/home/txing/.config/txing/rig/aws.credentials`
  - fill the `[town]` access keys

Concrete towns, rigs, and devices are AWS IoT things. The SSM catalog under
`/txing` stores only supported types and compatibility as leaf parameters, for
example `/txing/town/cloud/time/kind`.

Copy rig certificate material into:

```text
/home/txing/.config/txing/rig/certs/rig.cert.pem
/home/txing/.config/txing/rig/certs/rig.private.key
```

The stable no-checkout installer uses these files to bootstrap Greengrass Lite.

### 4. Prepare Greengrass Lite Configuration

Production rig supervision is AWS IoT Greengrass Nucleus Lite, not a custom
`rig.service` Python systemd unit. The stable rig path installs a
mise-provided Greengrass Lite payload and starts the default
`greengrass-lite.target`.

Before installing the service, the rig host must have:

- the AWS stacks and type catalog deployed with `just aws::deploy`
- a town thing created with `just aws::deploy-town town`
- a rig thing created with `just aws::deploy-rig <town-id> raspi server` or `just aws::deploy-rig <town-id> cloud aws`
- rig certificate material copied under
  `/home/txing/.config/txing/rig/certs/`

On a development machine with a checkout, create the rig certificate material.
The recipe resolves the configured rig thing from AWS IoT registry indexing,
attaches the stack IoT policy, and writes the certificate, public key, private
key, certificate ARN, and Amazon Root CA 1 under `config/certs/rig/`. That
directory is explicitly ignored by git.

```bash
just aws::cert <rig-id>
just rig::check <rig-id>
```

Copy the resulting `rig.cert.pem` and `rig.private.key` to the rig host under
`/home/txing/.config/txing/rig/certs/`.

`txing-greengrass-lite install <rig-id>` copies those files into
`/var/lib/greengrass/credentials`, downloads Amazon Root CA 1 into that same
directory, creates `ggcore`/`gg_component` if needed, and changes
`/var/lib/greengrass` ownership to `ggcore:ggcore`. It also generates
`/etc/greengrass/config.yaml` automatically by resolving the configured rig
thing through AWS IoT registry indexing, resolving the AWS IoT data and
credential-provider endpoints, and reading the
`GreengrassTokenExchangeRoleAlias` output from the base AWS stack.

### 5. Install Greengrass Lite And Deploy Rig Components

```bash
sudo env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-greengrass-lite install <rig-id>
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-rig-deploy auto
sudo systemctl status --with-dependencies greengrass-lite.target
```

`txing-greengrass-lite` installs and starts the standard Greengrass Lite
systemd units from the mise-provided payload. It does not manage the old custom
`rig.service` and it does not enable rig-type-specific host dependencies such as
Bluetooth. It rejects existing `/etc/greengrass`, `/var/lib/greengrass`,
`/run/greengrass`, or txing Greengrass tmpfiles state; remove old services
manually before using the fresh stable path.

`txing-greengrass-lite install <rig-id>` only installs Greengrass Lite, certificate
material, and bootstrap configuration. Txing components are delivered by the AWS
Greengrass deployment that targets the rig-type thing group. A clean host with
certificates, `/etc/greengrass/config.yaml`, network, and AWS access should join
that deployment after Greengrass Lite starts; no host-local `ggl-cli deploy` or
`/var/lib/greengrass/config.db` state is part of the production workflow.

Publish or update those rig-type deployments from the rig host:

```bash
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-rig-deploy auto
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-rig-deploy raspi
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-rig-deploy cloud
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-rig-deploy all
```

`txing-rig-deploy` resolves the local rig type on a rig host; explicit `raspi`,
`cloud`, and `all` targets are available. It uploads immutable artifacts under
`artifacts/<component>/<version>/`, creates Greengrass component versions from
the installed stable project version, and creates continuous deployments for
`txing-rig-type-raspi` and/or `txing-rig-type-cloud`.
The old host-local `ggl-cli deploy` path is kept only as
`just rig::deploy-local <rig-id>` for debugging Greengrass Lite itself.

Normal stable update:

```bash
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise upgrade
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-rig-deploy auto
```

The Greengrass Lite mise tool uses `latest` with the `greengrass-lite-v` tag
prefix. It only changes when this repository publishes a new
`greengrass-lite-v<upstream-version>` release.

For old rigs, cleanup is manual and intentionally not automated:

```bash
sudo systemctl stop ggl.dev.txing.rig.SparkplugManager.service ggl.dev.txing.rig.BleConnectivity.service ggl.dev.txing.rig.AwsConnectivity.service greengrass-lite.target || true
sudo systemctl disable greengrass-lite.target || true
sudo rm -rf /etc/greengrass /var/lib/greengrass /run/greengrass
sudo rm -f /etc/tmpfiles.d/txing-greengrass-lite.conf
sudo systemctl daemon-reload
sudo systemctl reset-failed
```

Inspect Greengrass service health with:

```bash
sudo systemctl status --with-dependencies greengrass-lite.target
sudo journalctl -a -f
sudo journalctl -a -f -u ggl.dev.txing.rig.SparkplugManager.service -u ggl.dev.txing.rig.BleConnectivity.service
sudo journalctl -a -f -u ggl.dev.txing.rig.SparkplugManager.service -u ggl.dev.txing.rig.AwsConnectivity.service
```

Restart the installed Greengrass Lite systemd units without deploying a new
component artifact with:

```bash
sudo systemctl restart greengrass-lite.target
```

Useful rig service commands:

```bash
sudo systemctl status --with-dependencies greengrass-lite.target
sudo journalctl -a -f
```

## Board Host

The board is the device-side Raspberry Pi. It runs the stable `txing-unit-daemon`
from GitHub Release artifacts, publishes the `board` and `video` named shadows,
runs the KVS sender, and exposes board MCP.

This guide assumes:

- Raspberry Pi Zero 2 W with Raspberry Pi OS Lite 64-bit
- Network is managed by `NetworkManager`
- the board remains headless
- AWS resources and the target device thing already exist
- daemon `.env` and certificate material have already been provisioned on the
  development Mac; see [Artifacts](./artifacts.md)

If your image is still using a different network manager, switch it before
enabling the read-only layout below.

Keep the board root filesystem writable until mise, the stable daemon, runtime
config, native sender, board service, and read-only-root configuration are in
place.

### 1. Create The Card

Use Raspberry Pi Imager:

- OS: Raspberry Pi OS Lite 64-bit
- hostname: `txing`
- user: `txing`
- SSH: enabled, preferably with the development machine's public key
- Wi-Fi: configured if the board is not using Ethernet
- locale/timezone: set for the installation location

Boot once with the default writable root filesystem and connect:

```bash
ssh txing
```

### 2. Install OS Packages

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
  git curl jq cmake pkg-config build-essential unzip \
  libssl-dev libcurl4-openssl-dev liblog4cplus-dev libsrtp2-dev \
  libusrsctp-dev libwebsockets-dev zlib1g-dev libcamera-dev \
  ca-certificates python3-venv python3-lgpio network-manager
```

If NetworkManager was newly installed or enabled, reconnect over the resulting
network path before continuing.

### 3. Install Mise

Use `mise` for developer CLIs that are missing, unavailable, or too old in the
OS package repository. `apt` should stay limited to OS libraries, headers, and
services needed by the board runtime.

```bash
mkdir -p "$HOME/.local/bin"
curl https://mise.run | sh
if ! grep -qxF 'eval "$($HOME/.local/bin/mise activate bash)"' "$HOME/.bashrc"; then
  echo 'eval "$($HOME/.local/bin/mise activate bash)"' >> "$HOME/.bashrc"
fi
eval "$("$HOME/.local/bin/mise" activate bash)"
mise use --global just@latest uv@latest aws-cli@latest
just --version
uv --version
aws --version
```

### 4. Copy Unit Daemon Config

From macOS:

```bash
test -r "$HOME/.config/txing/unit-daemon/.env"
test -r "$HOME/.config/txing/unit-daemon/private.pem.key"
COPYFILE_DISABLE=1 tar -C "$HOME/.config/txing" -czf /tmp/txing-unit-daemon-config.tgz unit-daemon
scp /tmp/txing-unit-daemon-config.tgz txing:/tmp/txing-unit-daemon-config.tgz
```

On the board:

```bash
install -d -m 700 "$HOME/.config/txing"
tar -xzf /tmp/txing-unit-daemon-config.tgz -C "$HOME/.config/txing"
chmod 700 "$HOME/.config/txing/unit-daemon"
chmod 600 "$HOME/.config/txing/unit-daemon/.env"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.arn"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.pem.crt"
chmod 600 "$HOME/.config/txing/unit-daemon/private.pem.key"
chmod 600 "$HOME/.config/txing/unit-daemon/public.pem.key"
chmod 644 "$HOME/.config/txing/unit-daemon/AmazonRootCA1.pem"
rm -f /tmp/txing-unit-daemon-config.tgz
```

### 5. Install Stable Unit Daemon

Install the stable daemon and systemd unit while root is still writable:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh | sudo bash -s -- stable
```

Verify:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -n 120 --no-pager
mise list
mise which txing-unit-daemon
```

Expected:

- `txing-unit-daemon` is listed from
  `~/.config/mise/conf.d/txing-unit-daemon.toml`;
- the executable lives under
  `~/.local/share/mise/installs/txing-unit-daemon/<version>/`;
- the daemon log includes `version=<stable-version>`, connects to MQTT, and
  publishes retained `board` online state.

### 6. Clone The Repo And Copy Board Runtime Config

The stable unit daemon does not require a source checkout. The board runtime and
native video sender still use the repository checkout.

```bash
export TXING_HOME="$HOME/txing"
git clone <repo-url> "$TXING_HOME"
cd "$TXING_HOME"
```

Populate:

- `config/aws.env`
- `config/aws.credentials`

Board-specific values to set in `config/aws.env`:

- `TXING_THING_ID` for board commands that operate on one enrolled device
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

### 7. Enable PWM Overlay

Append this to `/boot/firmware/config.txt` while `/boot/firmware` is writable:

```ini
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

### 8. Build The Native Sender And Python Runtime

Build the repo-owned KVS sender:

```bash
cd "$TXING_HOME"
just unit::board::submodules
just unit::board::build-native
```

The native sender build uses distro development packages for OpenSSL, libcurl,
libwebsockets, libsrtp2, usrsctp, zlib, and log4cplus. It does not compile the
AWS SDK's bundled third-party dependency sources.

Point `BOARD_VIDEO_SENDER_COMMAND` at the built binary, typically:

```bash
export BOARD_VIDEO_SENDER_COMMAND="$TXING_HOME/devices/unit/board/kvs_master/build/txing-board-kvs-master"
```

Build the Python runtime:

```bash
cd "$TXING_HOME"
python3 --version
just unit::board::build
```

Validate the board runtime AWS access:

```bash
cd "$TXING_HOME"
just unit::board::check
```

### 9. Smoke Test And Install The Board Service

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
just unit::board::install-service "$BOARD_VIDEO_SENDER_COMMAND"
sudo systemctl status board
sudo journalctl -u board -f
```

The generated unit:

- runs `board` as `root`
- loads `config/aws.env`
- enables `NetworkManager-wait-online.service`
- waits for clock synchronization before starting the AWS-backed video sender

### 10. Configure The Read-Only Root Filesystem

The current board runtime is compatible with a read-only root as long as these
writable paths stay on tmpfs:

- `/tmp`
  - board shadow mirror: `/tmp/txing_board_shadow.json`
  - board video sender state: `/tmp/txing_board_video_state.json`
  - MCP WebRTC socket: `/tmp/txing_board_mcp_webrtc.sock`
- `/var/tmp`
  - feature-channel mise install/cache/tmp state:
    `/var/tmp/txing/unit-daemon/`
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
tmpfs                     /var/tmp             tmpfs nosuid,nodev,exec,mode=1777,size=96M 0 0
tmpfs                     /var/log             tmpfs nosuid,nodev,mode=0755,size=16M 0 0
tmpfs                     /var/lib/NetworkManager tmpfs nosuid,nodev,mode=0755,size=16M 0 0
```

Add useful aliases to the `txing` user's shell config:

```bash
cat >> "$HOME/.bashrc" <<'EOF'
alias root-ro='sudo bash -c "rm -rf /var/tmp/* /tmp/* ; sync ; mount -o remount,ro /boot/firmware ; mount -o remount,ro /"'
alias root-rw='sudo bash -c "mount -o remount,rw /; mount -o remount,rw /boot/firmware; umount /var/tmp /tmp; sudo systemctl daemon-reload"'
EOF
```

Operational notes:

- Do all package installs, `mise` tool installs or updates, repo updates, rebuilds, and `systemd` unit changes while the root is writable.
- Switch back to read-only only after the runtime, native sender, and config files are in place.
- The `mise` binary, normal user mise config, and stable unit daemon install
  live under the `txing` user's home directory. Stable installs and upgrades
  must happen while the root filesystem is writable and use plain
  `mise upgrade`. Feature-channel daemon artifacts are upgraded and installed at
  service start into `/var/tmp/txing/unit-daemon/`, which is tmpfs-backed and
  executable, with the persistent stable install as fallback.
- AWS-backed services that install or connect over HTTPS during boot must wait
  for both network-online and clock synchronization. Otherwise TLS validation
  can fail before NTP corrects the board clock.
- If you need to change board code, env files, `/boot/firmware/config.txt`, the systemd unit, or `mise`-managed tooling later, use `root-rw`, make the change, restart the affected service, then `root-ro`.

### 11. Stable Maintenance

Use this during a writable-root maintenance window:

```bash
root-rw
sudo apt update
sudo apt dist-upgrade -y
mise upgrade
sudo systemctl restart txing-unit-daemon.service
root-ro
```

If a stable daemon release was just published and mise still resolves the
previous version:

```bash
root-rw
mise cache clear
mise upgrade
sudo systemctl restart txing-unit-daemon.service
root-ro
```

### 12. Final Verification

Switch to read-only mode and reboot:

```bash
root-ro
sudo reboot
```

After reconnecting:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -b -u txing-unit-daemon.service --no-pager
mise list
sudo systemctl status board
sudo journalctl -u board -f
```

Expected stable daemon behavior after reboot:

- root filesystem is read-only;
- `txing-unit-daemon.service` starts without a source checkout;
- daemon log includes `version=<stable-version>`;
- MQTT connects and retained `board` online state is published.

Useful board commands:

```bash
cd "$TXING_HOME"
just unit::board::run
just unit::board::once
just unit::board::motor-raw 240 240
just unit::board::motor-stop
```
