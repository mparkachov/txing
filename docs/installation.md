# Installation

This guide covers host setup. AWS bring-up and teardown live in [aws.md](./aws.md). Day-to-day development commands live in [development.md](./development.md).

## Shared Assumptions

- Development machines may use a repository checkout.
- Stable board hosts install release artifacts with `mise` and do not need a
  source checkout for the stable runtime path.
- Stable rig hosts receive txing components through Greengrass cloud
  deployments and do not need a source checkout, mise, AWS CLI, or AWS access
  keys.
- Project-local AWS config in a checkout stays under `config/`.
- Operator AWS config stays under `config/` in a checkout, or in an explicit
  operator config directory passed to deployment commands.
- `aws.env` is the single non-secret AWS/runtime config file for operator
  commands and board/rig setup.
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

Canonical rig installation, Greengrass Lite configuration, Bluetooth
permission, deployment, health-check, and cleanup instructions live in
[components/rig.md](./components/rig.md).

The short production flow is:

1. Install the upstream Greengrass Lite Debian package on the rig.
2. Add `gg_component` to the OS `bluetooth` group for `RIG_TYPE=raspi`.
3. Generate `config/certs/rig/` certificate material and `greengrass-lite.yaml`
   on the operator machine.
4. Copy `rig.cert.pem`, `rig.private.key`, `AmazonRootCA1.pem`, and
   `greengrass-lite.yaml` to the Greengrass locations on the rig.
5. Restart `greengrass-lite.target`.
6. Deploy txing components from the operator machine with
   `just rig::deploy-release latest all`.

Stable rig hosts receive txing components through Greengrass cloud deployments.
They do not install txing component binaries with mise, run AWS CLI, or store
AWS access keys.

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
