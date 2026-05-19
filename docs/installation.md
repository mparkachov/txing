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

Keep the board root filesystem writable until mise, the stable daemon, the
native KVS master release asset, runtime config, PWM overlay, and read-only-root
configuration are in place.

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
  curl jq \
  libssl-dev libcurl4-openssl-dev liblog4cplus-dev libsrtp2-dev \
  libusrsctp-dev libwebsockets-dev zlib1g-dev libcamera-dev \
  ca-certificates network-manager
```

If NetworkManager was newly installed or enabled, reconnect over the resulting
network path before continuing.

### 3. Install Mise

Use `mise` for txing release binaries and any operator CLIs that are missing,
unavailable, or too old in the OS package repository. `apt` should stay limited
to OS libraries, headers, and services needed by the board runtime.

```bash
sudo su -
mkdir -p "$HOME/.local/bin"
curl https://mise.run | sh
if ! grep -qxF 'eval "$($HOME/.local/bin/mise activate bash)"' "$HOME/.bashrc"; then
  echo 'eval "$($HOME/.local/bin/mise activate bash)"' >> "$HOME/.bashrc"
fi
eval "$("$HOME/.local/bin/mise" activate bash)"
mise --version
```

### 4. Copy Unit Daemon Config

From macOS:

```bash
just unit::cert <thing-id>
scp config/certs/unit/<thing-id>-daemon-config.tgz txing:/tmp/<thing-id>-daemon-config.tgz
```

On the board from the root shell:

```bash
install -d -m 700 "$HOME/.config/txing"
tar --no-same-owner -xzf /tmp/<thing-id>-daemon-config.tgz -C "$HOME/.config/txing"
chmod 700 "$HOME/.config/txing/unit-daemon"
chmod 600 "$HOME/.config/txing/unit-daemon/.env"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.arn"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.pem.crt"
chmod 600 "$HOME/.config/txing/unit-daemon/private.pem.key"
chmod 600 "$HOME/.config/txing/unit-daemon/public.pem.key"
chmod 644 "$HOME/.config/txing/unit-daemon/AmazonRootCA1.pem"
rm -f /tmp/<thing-id>-daemon-config.tgz
```

For existing devices provisioned before the daemon KVS permissions were added,
refresh the per-device daemon role policy from the operator machine before
restarting the board:

```bash
just unit::daemon::role-policy <thing-id>
```

### 5. Install Stable Unit Daemon

Install the stable daemon, KVS master, and systemd unit from the root shell
while root is still writable:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh -o /tmp/txing-install-systemd.sh
bash /tmp/txing-install-systemd.sh stable
```

The installer may run before the daemon `.env` and certificate files are copied.
Those files must exist before the service can run successfully.

Verify:

```bash
systemctl status --no-pager -l txing-unit-daemon.service
journalctl -u txing-unit-daemon.service -n 120 --no-pager
/root/.local/bin/mise list
/root/.local/bin/mise which txing-unit-daemon
/root/.local/bin/mise which txing-board-kvs-master
```

Expected:

- `txing-unit-daemon` is listed from
  `~/.config/mise/conf.d/txing-unit-daemon.toml`;
- `txing-board-kvs-master` is listed from the same mise config;
- the executable lives under
  `~/.local/share/mise/installs/txing-unit-daemon/<version>/`;
- `txing-board-kvs-master` lives under
  `~/.local/share/mise/installs/txing-board-kvs-master/<version>/`;
- the daemon log includes `version=<stable-version>`, connects to MQTT,
  publishes retained `board` and MQTT-only `mcp` state, and starts the native
  KVS master when the device declares the `video` capability.

### 6. Configure Runtime Options

The copied daemon `.env` is enough for the default video path:

- `TXING_KVS_MASTER_COMMAND` defaults to `txing-board-kvs-master`.
- `TXING_BOARD_VIDEO_REGION` falls back to `BOARD_VIDEO_REGION`, then
  `AWS_REGION`.
- `TXING_BOARD_VIDEO_CHANNEL_NAME` falls back to
  `BOARD_VIDEO_CHANNEL_NAME`, then `<thing-id>-board-video`.

Only add overrides to `$HOME/.config/txing/unit-daemon/.env` when the board
needs non-default values.

For the current default chassis, the measured motor bring-up values are:

```bash
TXING_MOTOR_CMD_RAW_MIN_SPEED=50
TXING_MOTOR_CMD_RAW_MAX_SPEED=250
```

### 7. Enable PWM Overlay

Append this to `/boot/firmware/config.txt` while `/boot/firmware` is writable:

```ini
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

Restart after changing the overlay so the PWM devices exist before motor
validation.

### 8. Validate Stable Runtime

After the reboot or service restart:

```bash
systemctl status --no-pager -l txing-unit-daemon.service
journalctl -u txing-unit-daemon.service -n 160 --no-pager
/root/.local/bin/mise which txing-unit-daemon
/root/.local/bin/mise which txing-board-kvs-master
```

Expected:

- the daemon resolves both release-installed commands through mise;
- the daemon publishes retained `board`, MQTT-only `mcp`, and `video`
  descriptor/status state;
- the `video` named shadow mirrors the retained video state;
- REDCON can reach `1` after rig projection sees board, MCP, and video ready.

### 9. Configure The Read-Only Root Filesystem

The current board runtime is compatible with a read-only root as long as these
writable paths stay on tmpfs:

- `/tmp`
  - transient runtime and OS scratch space
- `/var/tmp`
  - transient runtime scratch space
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

Add useful aliases to the root shell config:

```bash
cat >> "$HOME/.bashrc" <<'EOF'
alias root-ro='bash -c "rm -rf /var/tmp/* /tmp/* ; sync ; mount -o remount,ro /boot/firmware ; mount -o remount,ro /"'
alias root-rw='bash -c "mount -o remount,rw /; mount -o remount,rw /boot/firmware; umount /var/tmp /tmp; systemctl daemon-reload"'
EOF
```

Operational notes:

- Do all package installs, `mise` tool installs or updates, daemon config
  changes, and `systemd` unit changes while the root is writable.
- Switch back to read-only only after the runtime, native KVS master, and config
  files are in place.
- The `mise` binary, mise config, daemon config, stable daemon install, and
  feature daemon overlay are root-owned. The service runs as root with
  `HOME=/root`, so feature-channel `mise` pre-start updates never write into
  `/home/txing`.
- AWS-backed services that install or connect over HTTPS during boot must wait
  for both network-online and clock synchronization. Otherwise TLS validation
  can fail before NTP corrects the board clock.
- If you need to change env files, `/boot/firmware/config.txt`, the systemd
  unit, or `mise`-managed tooling later, use `root-rw`, make the change,
  restart the affected service, then `root-ro`.

### 10. Stable Maintenance

Use this during a writable-root maintenance window:

```bash
root-rw
apt update
apt dist-upgrade -y
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh -o /tmp/txing-install-systemd.sh
bash /tmp/txing-install-systemd.sh stable
root-ro
```

If a stable daemon release was just published and mise still resolves the
previous version:

```bash
root-rw
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh -o /tmp/txing-install-systemd.sh
/root/.local/bin/mise cache clear
bash /tmp/txing-install-systemd.sh stable
root-ro
```

### 11. Final Verification

Switch to read-only mode and reboot:

```bash
root-ro
sudo reboot
```

After reconnecting:

```bash
systemctl status --no-pager -l txing-unit-daemon.service
journalctl -u txing-unit-daemon.service -b -u txing-unit-daemon.service --no-pager
/root/.local/bin/mise list
/root/.local/bin/mise which txing-unit-daemon
/root/.local/bin/mise which txing-board-kvs-master
```

Expected stable daemon behavior after reboot:

- root filesystem is read-only;
- `txing-unit-daemon.service` starts without a source checkout;
- daemon log includes `version=<stable-version>`;
- MQTT connects and retained `board`, MQTT-only `mcp`, and `video` state is
  published;
- the KVS master child reaches `TXING_KVS_READY` when camera and signaling are
  available.
