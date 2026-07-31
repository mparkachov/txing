# Board (Debian, frozen)

These boards run the root-owned Go `txing-unit-daemon` plus the native
`txing-unit-kvs-master` and `txing-unit-hardware-worker` as systemd services.

> **Frozen material.** This document describes the Debian and systemd board
> install that predates the move to Alpine. It is kept so the boards not yet
> reimaged remain serviceable and so their history is legible. It is not current
> practice and receives no further investment; see
> [Board OS: Alpine only, Debian frozen](../constraints/board-os-alpine-only.md).
>
> A board described here cannot be upgraded onto the current protocol. Camera
> builds are Alpine-only, so its KVS master cannot be rebuilt, and its local gRPC
> packages `txing.unit.board_video.v1` and `txing.unit.hardware.v1` are
> wire-incompatible with the current `txing.board.*` contracts. Moving such a
> board forward means reimaging it to Alpine and following
> [Board](./board.md).
>
> The device behaviour contract, retained topics, REDCON ladder, and runtime
> interfaces are **not** duplicated here. They are device-agnostic and live in
> [Board](./board.md); only the Debian-specific install and maintenance steps
> are frozen below.

## Fresh Board Install

Assumptions:

- Raspberry Pi Zero 2 W
- Raspberry Pi OS Lite 64-bit, Trixie
- `NetworkManager` manages networking
- AWS resources and the target unit thing already exist
- daemon environment/certificate archive has been generated on the operator
  machine

### 1. Create The Card

Use Raspberry Pi Imager:

- OS: Raspberry Pi OS Lite 64-bit
- hostname: `txing`
- user: `txing`
- SSH enabled
- Wi-Fi configured if the board is not using Ethernet
- locale/timezone set for the installation location

Boot once with the default writable root filesystem, connect as `txing`, then
enter a root shell for the remaining host setup:

```bash
sudo su -
```

### 2. Install OS Packages

```bash
apt update
apt full-upgrade -y
apt install -y \
  curl jq \
  libssl-dev libcurl4-openssl-dev liblog4cplus-dev libsrtp2-dev \
  libusrsctp-dev libwebsockets-dev zlib1g-dev libcamera-dev \
  libprotobuf-dev protobuf-compiler libgrpc++-dev protobuf-compiler-grpc \
  ca-certificates network-manager
```

If NetworkManager was newly installed or enabled, reconnect over the resulting
network path before continuing.

Unit releases are built in the pinned Alpine musl container (the board build
contract): `txing-unit-daemon` and `txing-unit-hardware-worker` are fully
static musl binaries that run unchanged on both Raspberry Pi OS (Debian) and
Alpine hosts, while `txing-unit-kvs-master` is dynamically linked against musl
and stock Alpine libcamera and therefore runs on Alpine hosts only.

For existing Debian boards this means: the daemon and hardware worker keep
updating normally, but the camera freezes at the last Debian-built KVS master
release (which links `libcamera.so.0.7` from the packages above). Never
upgrade `txing-unit-kvs-master` past that release on a Debian board — newer
camera builds only run after the board is reimaged to Alpine. The manual
install checks below run `ldd` on the resolved binaries before systemd is
restarted.

### 3. Install Mise

Install `mise` in the root shell:

```bash
mkdir -p "$HOME/.local/bin"
curl https://mise.run | sh
if ! grep -qxF 'eval "$($HOME/.local/bin/mise activate bash)"' "$HOME/.bashrc"; then
  echo 'eval "$($HOME/.local/bin/mise activate bash)"' >> "$HOME/.bashrc"
fi
eval "$("$HOME/.local/bin/mise" activate bash)"
mise --version
```

### 4. Generate And Copy Daemon Config

On the operator machine:

```bash
just aws::cert <thing-id>
scp certs/<thing-id>/<thing-id>-daemon-config.tgz txing:/tmp/<thing-id>-daemon-config.tgz
```

On the board from the root shell:

```bash
install -d -m 700 "$HOME/.config/txing/unit-daemon"
tar --no-same-owner -xzf /tmp/<thing-id>-daemon-config.tgz -C "$HOME/.config/txing/unit-daemon"
chmod 700 "$HOME/.config/txing/unit-daemon"
chmod 600 "$HOME/.config/txing/unit-daemon/daemon.env"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.arn"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.pem.crt"
chmod 600 "$HOME/.config/txing/unit-daemon/private.pem.key"
chmod 600 "$HOME/.config/txing/unit-daemon/public.pem.key"
chmod 644 "$HOME/.config/txing/unit-daemon/AmazonRootCA1.pem"
rm -f /tmp/<thing-id>-daemon-config.tgz
```

For existing devices provisioned before daemon KVS permissions were added,
refresh the per-device daemon role policy from the operator machine:

```bash
just unit::board::role-policy <thing-id>
```

### 5. Install Runtime

Run from the board root shell while root is writable.
`minimum_release_age = "0s"` opts out of mise's default 24-hour release-age
filter: boards install first-party releases minutes after they are
published, and with the default filter `latest` resolves to nothing.

```bash
install -d -m 700 /root/.config/mise/conf.d /root/.local/share/mise
cat >/root/.config/mise/conf.d/txing-unit-daemon.toml <<'EOF'
[settings]
fetch_remote_versions_cache = "10m"
minimum_release_age = "0s"

[tool_alias]
txing-unit-daemon = "github:mparkachov/txing"
txing-unit-kvs-master = "github:mparkachov/txing"
txing-unit-hardware-worker = "github:mparkachov/txing"

[tools.txing-unit-daemon]
version = "latest"
version_prefix = "unit-v"
asset_pattern = "txing-unit-daemon-linux-aarch64.tar.gz"

[tools.txing-unit-kvs-master]
version = "latest"
version_prefix = "unit-v"
asset_pattern = "txing-unit-kvs-master-linux-aarch64.tar.gz"

[tools.txing-unit-hardware-worker]
version = "latest"
version_prefix = "unit-v"
asset_pattern = "txing-unit-hardware-worker-linux-aarch64.tar.gz"
EOF

MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise install txing-unit-daemon@latest txing-unit-kvs-master@latest txing-unit-hardware-worker@latest
```

Check the resolved binaries before writing the service:

```bash
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master --version
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker --version
ldd /root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon || true
ldd /root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker || true
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master | grep -F "libcamera.so.0.7"
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master | grep -F "libcamera-base.so.0.7"
```

The daemon and hardware worker are static: on a Debian board `ldd` reports
`not a dynamic executable` or `statically linked` for them, and that is the
healthy state. The KVS master checks apply to the frozen Debian-built camera
release: it must resolve every library and link `libcamera.so.0.7` and
`libcamera-base.so.0.7`. If its `ldd` reports `not found` libraries or an
older libcamera soname, the installed asset was built for the wrong board
image and must be replaced with the last Debian-built release.

Write the root-owned systemd units and group them under `txing-unit.target`.
The daemon owns the board-video bridge socket; the KVS master connects to it as
a separate service. The hardware worker owns the UnitHardware socket; the daemon
connects to it as a client and degrades if it is unavailable.

```bash
cat >/etc/systemd/system/txing-unit-daemon.service <<'EOF'
[Unit]
Description=Txing Unit Daemon
Wants=network-online.target systemd-time-wait-sync.service txing-unit-hardware-worker.service
After=network-online.target systemd-time-wait-sync.service time-sync.target txing-unit-hardware-worker.service
PartOf=txing-unit.target
StartLimitIntervalSec=10min
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=/root
KillSignal=SIGINT
TimeoutStartSec=180
TimeoutStopSec=30
Restart=on-failure
RestartSec=5

Environment=TXING_DAEMON_CONFIG_DIR=/root/.config/txing/unit-daemon
Environment=HOME=/root

ExecStartPre=/usr/bin/test -x /root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon
ExecStartPre=-/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
ExecStart=/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon

[Install]
WantedBy=txing-unit.target
EOF

cat >/etc/systemd/system/txing-unit-hardware-worker.service <<'EOF'
[Unit]
Description=Txing Unit Hardware Worker
PartOf=txing-unit.target
Before=txing-unit-daemon.service
StartLimitIntervalSec=10min
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=/root
KillSignal=SIGINT
TimeoutStartSec=30
TimeoutStopSec=10
Restart=on-failure
RestartSec=2
RuntimeDirectory=txing-unit-hardware-worker
RuntimeDirectoryMode=0755

EnvironmentFile=/root/.config/txing/unit-daemon/daemon.env
Environment=HOME=/root

ExecStartPre=/usr/bin/test -x /root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker
ExecStartPre=-/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker --version
ExecStart=/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker

[Install]
WantedBy=txing-unit.target
EOF

cat >/etc/systemd/system/txing-unit-kvs-master.service <<'EOF'
[Unit]
Description=Txing Board KVS Master
Wants=network-online.target txing-unit-daemon.service
After=network-online.target txing-unit-daemon.service
PartOf=txing-unit.target
StartLimitIntervalSec=10min
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=/root
KillSignal=SIGINT
TimeoutStartSec=180
TimeoutStopSec=30
Restart=on-failure
RestartSec=5

Environment=HOME=/root
Environment=TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH=/run/txing-unit-daemon/board-video-bridge.sock

ExecStartPre=/usr/bin/test -x /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master
ExecStartPre=-/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master --version
ExecStart=/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master

[Install]
WantedBy=txing-unit.target
EOF

cat >/etc/systemd/system/txing-unit.target <<'EOF'
[Unit]
Description=Txing Board Runtime
Wants=txing-unit-daemon.service txing-unit-kvs-master.service txing-unit-hardware-worker.service
After=network-online.target systemd-time-wait-sync.service time-sync.target

[Install]
WantedBy=multi-user.target
EOF

if systemctl list-unit-files NetworkManager-wait-online.service --no-legend --no-pager 2>/dev/null \
  | grep -q '^NetworkManager-wait-online\.service[[:space:]]'; then
  systemctl enable NetworkManager-wait-online.service
fi
systemctl daemon-reload
systemctl enable txing-unit.target
systemctl enable txing-unit-daemon.service
systemctl enable txing-unit-kvs-master.service
systemctl enable txing-unit-hardware-worker.service
systemctl restart txing-unit-hardware-worker.service
systemctl restart txing-unit-daemon.service
systemctl restart txing-unit-kvs-master.service
systemctl start txing-unit.target
```

Verify:

```bash
systemctl status --no-pager -l txing-unit.target
systemctl status --no-pager -l txing-unit-daemon.service
systemctl status --no-pager -l txing-unit-kvs-master.service
systemctl status --no-pager -l txing-unit-hardware-worker.service
journalctl -u txing-unit-daemon.service -n 160 --no-pager
journalctl -u txing-unit-kvs-master.service -n 160 --no-pager
journalctl -u txing-unit-hardware-worker.service -n 160 --no-pager
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master --version
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker --version
```

Expected:

- `txing-unit.target` is active and includes all three board services
- stopping or restarting `txing-unit.target` propagates to all three services
- the daemon log includes `version=<release-version>`
- the daemon binds `/run/txing-unit-daemon/board-video-bridge.sock`
- the hardware worker binds `/run/txing-unit-hardware-worker/unit-hardware.sock`
- the worker logs version and local actuator readiness or a clear hardware
  error
- MQTT connects
- retained `board`, dynamic `mcp`, and `video` state is published
- the KVS master service reaches READY over the bridge when camera and
  signaling are available
- REDCON can reach `1` after Sparkplug projection sees fresh `board`, `mcp`,
  and `video` capability state

### 6. Enable PWM Overlay

Append this to `/boot/firmware/config.txt` while `/boot/firmware` is writable:

```ini
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

Restart after changing the overlay so PWM devices exist before motor
validation.

### 7. Configure Read-Only Root

The runtime is compatible with read-only root as long as these paths stay
writable on tmpfs:

- `/tmp`
- `/var/tmp`
- `/var/log`
- `/var/lib/NetworkManager`

The native KVS worker keeps the signaling cache in memory and does not depend
on the SDK default `.SignalingCache_v1` file.

Make `/etc/resolv.conf` point at NetworkManager's runtime resolver output
before switching root to read-only. With a regular file on read-only root,
NetworkManager cannot refresh resolver configuration after boot and DNS may
fail even when the network is otherwise online:

```bash
rm -f /etc/resolv.conf
ln -s /run/NetworkManager/resolv.conf /etc/resolv.conf
readlink /etc/resolv.conf
getent hosts example.com
```

Replace `PARTUUID` placeholders with values from
`lsblk -o NAME,PARTUUID,MOUNTPOINT`, then use this `fstab` layout:

```fstab
proc            /proc           proc    defaults          0       0
PARTUUID=<boot-partuuid>  /boot/firmware  vfat    defaults,ro,noatime         0       2
PARTUUID=<root-partuuid>  /               ext4    defaults,ro,noatime         0       1
tmpfs                     /tmp                 tmpfs nosuid,nodev,mode=1777,size=32M 0 0
tmpfs                     /var/tmp             tmpfs nosuid,nodev,exec,mode=1777,size=96M 0 0
tmpfs                     /var/log             tmpfs nosuid,nodev,mode=0755,size=16M 0 0
tmpfs                     /var/lib/NetworkManager tmpfs nosuid,nodev,mode=0755,size=16M 0 0
```

Useful  shell aliases:

```bash
cat >> "$HOME/.bash_aliases" <<'EOF'
alias root-rw='sudo bash -c "mount -o remount,rw /; mount -o remount,rw /boot/firmware; umount /var/tmp; umount /tmp; sudo systemctl daemon-reload"'
alias root-ro='sudo bash -c "rm -rf /var/tmp/* /tmp/* ; sync; mount -o remount,ro /boot/firmware ; mount -o remount,ro / ; mount /tmp ; mount /var/tmp"'
EOF
```

Operational rules:

- do package installs, `mise` installs/updates, daemon config changes, and
  systemd unit changes while root is writable
- switch back to read-only only after runtime binaries, native workers, and
  config files are in place
- the service runs as root with `HOME=/root`
- AWS-backed services wait for network-online and clock synchronization so TLS
  validation does not race NTP
- the hardware worker neutralizes motors internally; systemd restart latency is
  supervision only, not the motion-control safety layer

### 8. Final Reboot Check

```bash
root-ro
reboot
```

After reconnecting:

```bash
systemctl status --no-pager -l txing-unit.target
systemctl status --no-pager -l txing-unit-daemon.service
systemctl status --no-pager -l txing-unit-kvs-master.service
systemctl status --no-pager -l txing-unit-hardware-worker.service
journalctl -u txing-unit-daemon.service -b --no-pager
journalctl -u txing-unit-kvs-master.service -b --no-pager
journalctl -u txing-unit-hardware-worker.service -b --no-pager
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master --version
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker --version
readlink /etc/resolv.conf
getent hosts example.com
```

Expected:

- root filesystem is read-only
- `/etc/resolv.conf` points at `/run/NetworkManager/resolv.conf` and DNS
  resolves through NetworkManager
- `txing-unit.target` is active
- `txing-unit-daemon.service` starts without a source checkout
- `txing-unit-kvs-master.service` starts without a source checkout
- `txing-unit-hardware-worker.service` starts without a source checkout
- daemon log includes `version=<release-version>`
- MQTT connects and retained board/MCP/video state is published

## Maintenance

Board update during a writable-root maintenance window. Publish a new immutable
`unit-vX.Y.Z` release first, and replace old root-owned mise config manually if
it does not include `version_prefix = "unit-v"`:

On a Debian board, upgrade only the static pair — the camera stays frozen at
the last Debian-built KVS master release (Alpine-built camera binaries do not
run on Debian):

```bash
sudo su -
root-rw
apt update
apt dist-upgrade -y
MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise upgrade txing-unit-daemon txing-unit-hardware-worker
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master --version
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker --version
ldd /root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker || true
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master | grep -F "libcamera.so.0.7"
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master | grep -F "libcamera-base.so.0.7"
sync
reboot
```

The static daemon and hardware worker depend only on the kernel, so they stay
current on Debian indefinitely. The board rejoins the camera update stream
when it is reimaged to Alpine.

Boards upgraded from the pre-unit target naming must also remove the retired
systemd units during a writable-root maintenance window. After installing the
new `txing-unit.target` units and before rebooting:

```bash
systemctl disable --now txing-board.target txing-board-kvs-master.service || true
rm -f /etc/systemd/system/txing-board.target
rm -f /etc/systemd/system/txing-board-kvs-master.service
systemctl daemon-reload
```
