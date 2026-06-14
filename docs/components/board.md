# Board

The board is the device-side Raspberry Pi. It is power-switched by the MCU,
runs the root-owned Go `txing-unit-daemon` and native
`txing-unit-kvs-master` plus `txing-unit-hardware-worker` systemd services,
publishes board-owned runtime state, and exposes board MCP for motion control.

## Responsibilities

- publish the `board` named shadow
- publish the `video` named shadow mirror
- publish retained video descriptor/status topics under
  `txings/<device_id>/video/*`
- publish retained MCP descriptor/status topics under
  `txings/<device_id>/mcp/*`
- publish retained v2 capability state for `board`, `mcp`, and `video`
- serve the local BoardVideoBridge gRPC socket for native KVS worker config,
  temporary credentials, video state, and MCP forwarding
- connect to the local UnitHardware gRPC socket for actuator readiness,
  `cmd_vel` application, and local motor stop requests
- subscribe to Sparkplug `DCMD.redcon` and halt locally on `redcon=4`
- enforce MCP active-control ownership for actuator tools
- send hardware stop requests on active-control expiry, session close,
  transport switch, REDCON `4`, and daemon shutdown
- neutralize motors inside the hardware worker on command expiry, explicit stop,
  shutdown, and hardware errors

## REDCON Contract

For the current `unit` device type:

- `REDCON 4`: BLE GATT is confirmed commandable and the unit is in the sleep state.
- `REDCON 3`: BLE GATT is confirmed commandable and MCU-controlled wakeup power/D1 is enabled.
- `REDCON 2`: board and MCP are available; video is unavailable or not ready.
- `REDCON 1`: board, MCP, and video are available.

The board publishes retained v2 capability state for `board`, `mcp`, and
`video`. `txing-sparkplug-manager` consumes that retained state directly for
REDCON projection. When BLE confirms REDCON `4` / `power=false`, Sparkplug
projection clears board-owned capabilities and does not reuse stale retained
board state on the next wake; fresh board daemon state must arrive before
`board`, `mcp`, or `video` become available again.

## Retained AWS IoT Topics

Board MQTT clients use MQTT 5 for AWS IoT retained service state. Dynamic
freshness signals are retained with a MQTT 5 Message Expiry Interval equal to
`TXING_CAPABILITY_TTL_SECONDS`, which defaults to `150` seconds:

- `txings/<device_id>/capability/v2/state`
- `txings/<device_id>/mcp/status`
- `txings/<device_id>/video/status`

Descriptor topics are retained discovery/config records and must not expire:

- `txings/<device_id>/mcp/descriptor`
- `txings/<device_id>/video/descriptor`

Existing retained AWS IoT messages that were published before expiry was added
are replaced only when the daemon republishes the same topic. Orphaned old
retained topics, or topics for devices that no longer publish, require manual
AWS IoT retained-message cleanup if they matter operationally.

## Runtime Interfaces

### Board Shadow

The board-owned named shadow is a reported-only read model:

```json
{
  "state": {
    "reported": {
      "power": true,
      "wifi": {
        "online": true,
        "ipv4": "192.168.1.25",
        "ipv6": "2001:db8::25"
      }
    }
  }
}
```

Notes:

- `reported.power=false` is best-effort clean shutdown state only.
- stale `power=true` or `wifi.online=true` is not authoritative after a hard
  power cut.

### Video

Current video is headless AWS Kinesis Video Streams WebRTC:

- signaling channel: `<device_id>-board-video`
- browser route: `/<town>/<rig>/<device>/video`
- retained topics:
  - `txings/<device_id>/video/descriptor`: retained, no expiry
  - `txings/<device_id>/video/status`: retained dynamic state, expires after
    `TXING_CAPABILITY_TTL_SECONDS`
- named shadow mirror: `video`
- worker binary: `txing-unit-kvs-master`

The native worker owns camera capture, H.264 encode, AWS KVS master behavior,
WebRTC peer connections, and data-channel transport. The Go daemon owns
worker configuration, KVS temporary credentials, readiness interpretation,
retained state publication, MCP business logic, and actuator policy.

The daemon and native worker communicate through the local
BoardVideoBridge gRPC contract:
[docs/contracts/board-video-bridge.md](../contracts/board-video-bridge.md).
The proto source is
`devices/unit/proto/txing/unit/board_video/v1/board_video.proto`.

By default the daemon asks the native worker to use KVS dual-stack endpoints
and IPv6-preferred TURN behavior. `TXING_KVS_DISABLE_IPV4_TURN=true` is a
validation override, not the normal runtime setting.

The worker reports coarse state through `ReportVideoState`. `READY` means the
worker is ready enough for the daemon to advertise WebRTC MCP transport; it is
not a media-quality guarantee.

The board video contract is documented in
[devices/unit/docs/board-video.md](../../devices/unit/docs/board-video.md).

### Motion Hardware

Motion commands use strict ROS `Twist`/`cmd_vel` semantics. The daemon owns MCP
active-control, epoch validation, REDCON handling, and all cloud publication.
The root-owned `txing-unit-hardware-worker` owns motor hardware devices,
calibration, differential tank mixing, PWM/GPIO output, local hardware
readiness, and motor neutralization.

The daemon is a gRPC client and the worker is a gRPC server on the local Unix
domain socket:

```text
/run/txing-unit-hardware-worker/unit-hardware.sock
```

The worker API is `txing.unit.hardware.v1.UnitHardware`:

- `GetStatus`
- `ApplyVelocity`
- `Stop`

Every `ApplyVelocity` carries a canonical `deadline_unix_ms`. v1 accepts only
`linear.x` and `angular.z`; non-zero unsupported `Twist` axes are rejected.
The worker may clamp command deadlines to its configured watchdog timeout. If
the worker is unavailable or reports not ready, the daemon rejects actuator MCP
tools as unavailable after active-control validation.

The hardware worker contract is documented in
[docs/contracts/unit-hardware-worker.md](../contracts/unit-hardware-worker.md).

### MCP

MCP protocol version is `2026-05-19`.

Current tool surface:

- `control.get_state`
- `control.activate`
- `control.renew_active`
- `control.release_active`
- `cmd_vel.publish`
- `cmd_vel.stop`
- `robot.get_state`

Dynamic transport rules:

- REDCON `1`: MCP is WebRTC data-channel only on the board video KVS media
  session, with label `txing.mcp.v1`.
- REDCON `2`: MCP is MQTT JSON-RPC only.
- MQTT MCP requests are rejected while the daemon advertises WebRTC-only MCP.
- If WebRTC MCP fails while WebRTC-only MCP is advertised, browser control stays
  unavailable until the daemon publishes an MQTT-only descriptor.
- Legacy descriptors without `transports` parse as MQTT-only.

Video-ready descriptor shape:

```json
{
  "serviceId": "mcp",
  "mcpProtocolVersion": "2026-05-19",
  "transports": [
    {
      "type": "webrtc-datachannel",
      "priority": 10,
      "sessionKind": "media",
      "signaling": "aws-kvs",
      "channelName": "<device_id>-board-video",
      "region": "<aws-region>",
      "label": "txing.mcp.v1"
    }
  ]
}
```

Video-unavailable descriptor shape:

```json
{
  "serviceId": "mcp",
  "mcpProtocolVersion": "2026-05-19",
  "transports": [
    {
      "type": "mqtt-jsonrpc",
      "priority": 100,
      "topicRoot": "txings/<device_id>/mcp"
    }
  ]
}
```

### Active Control

The daemon maintains one active control slot. Many MCP sessions may observe,
but only the active session may execute actuator tools.

`control.activate` arguments:

```json
{
  "actor": "txing-web",
  "takeover": true
}
```

Rules:

- no active owner: `control.activate` succeeds
- same session already active: returns current active state
- another session active and `takeover` is not `true`: returns active-control
  busy
- another session active and `takeover: true`: stops motors, increments
  `epoch`, replaces the active owner, and publishes status
- displaced sessions remain connected as observers
- `renew_active`, `release_active`, `cmd_vel.publish`, and `cmd_vel.stop` all
  enforce session and epoch

`robot.get_state` and retained MCP status include active-control owner metadata:

```json
{
  "activeControl": {
    "sessionId": "session-id",
    "actor": "txing-web",
    "transport": "webrtc-datachannel",
    "sinceMs": 1770000000000,
    "expiresAtMs": 1770000005000,
    "epoch": 42
  }
}
```

## Runtime Configuration

Deployed boards use root-owned config:

```text
/root/.config/txing/unit-daemon/daemon.env
/root/.config/txing/unit-daemon/AmazonRootCA1.pem
/root/.config/txing/unit-daemon/certificate.arn
/root/.config/txing/unit-daemon/certificate.pem.crt
/root/.config/txing/unit-daemon/private.pem.key
/root/.config/txing/unit-daemon/public.pem.key
```

`daemon.env` is a systemd-compatible environment file rendered from
`devices/unit/daemon/daemon.env.template`. It uses plain `KEY=value` lines so
both `txing-unit-hardware-worker.service` and the daemon can consume the same
root-owned file. Certificate paths are omitted by default; the daemon derives
colocated paths from the loaded `daemon.env` directory. For manual shell export,
use `set -a; . /root/.config/txing/unit-daemon/daemon.env; set +a`.

Default runtime inputs include:

- `AWS_REGION`
- `TXING_DAEMON_CAPABILITIES`
- `TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH`
- `TXING_BOARD_VIDEO_CHANNEL_NAME`
- `TXING_KVS_PREFER_IPV6`
- `TXING_KVS_DISABLE_IPV4_TURN`
- `TXING_HARDWARE_WORKER_SOCKET_PATH`
- `TXING_HARDWARE_WORKER_TIMEOUT_MS`
- `TXING_MOTOR_*`
- CloudWatch log configuration

Motor calibration supports per-track output trim through the shared
`daemon.env` file. Values are numeric percentages in `(0, 100]`; omit the `%`
sign. For example, if straight driving drifts left because the right track is
stronger, reduce the right side:

```text
TXING_MOTOR_LEFT_TRACK_POWER_PERCENT=100
TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT=98
```

Track power trim is board-local physical calibration. It is applied after
logical tank mixing and before raw PWM scaling, so user-facing
`motion.leftSpeed` and `motion.rightSpeed` still report the untrimmed logical
command.

The default video channel is `<thing_id>-board-video`. The default bridge
socket path is `/run/txing-unit-daemon/board-video-bridge.sock`. Existing
boards with an older generated `daemon.env` must remove leading `export `
prefixes for systemd `EnvironmentFile=` compatibility and add
`TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH`,
`TXING_HARDWARE_WORKER_SOCKET_PATH`, and
`TXING_HARDWARE_WORKER_TIMEOUT_MS`; generated config files are not overwritten
by binary upgrades. Existing boards must also add
`TXING_MOTOR_LEFT_TRACK_POWER_PERCENT=100` and
`TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT=100` if their `daemon.env` predates
track power trim. The daemon ignores `TXING_MOTOR_*`; those values are consumed
by `txing-unit-hardware-worker` when its systemd unit loads the same root-owned
env file.

## Release Artifacts

Boards install three GitHub Release assets through root-owned `mise`:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-unit-kvs-master-linux-aarch64.tar.gz
txing-unit-hardware-worker-linux-aarch64.tar.gz
```

Each archive contains one root-level executable:

```text
txing-unit-daemon
txing-unit-kvs-master
txing-unit-hardware-worker
```

Boards use root's persistent mise config and install tree:

```text
/root/.config/mise/conf.d/txing-unit-daemon.toml
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon
/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker
/root/.local/share/mise/installs/txing-unit-daemon/
/root/.local/share/mise/installs/txing-unit-kvs-master/
/root/.local/share/mise/installs/txing-unit-hardware-worker/
```

Service starts are offline by design. Restarting
`txing-unit-daemon.service` does not install or upgrade tools. If a board needs
new binaries, log into the board, enter a root shell, switch root to writable
mode, run root-owned `mise upgrade`, and reboot.

Unit tools are released from the `unit` component stream. Root-owned `mise`
configs must set `version_prefix = "unit-v"` so `latest` resolves from
`unit-v*` GitHub Releases instead of the repository-wide latest release. This
release model is forward-only; replace old board configs manually if they do
not include the component prefix.

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

The release KVS master is built for Raspberry Pi OS Trixie and should link
against `libcamera.so.0.7` and `libcamera-base.so.0.7`. The manual install
checks below run `ldd` on the resolved binaries before systemd is restarted. If
`ldd` reports `libcamera.so.0.2` or `libcamera.so.0.4`, the release asset was
built against the wrong board image and must be replaced.

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
just unit::daemon::role-policy <thing-id>
```

### 5. Install Runtime

Run from the board root shell while root is writable:

```bash
install -d -m 700 /root/.config/mise/conf.d /root/.local/share/mise
cat >/root/.config/mise/conf.d/txing-unit-daemon.toml <<'EOF'
[settings]
fetch_remote_versions_cache = "10m"

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
ldd /root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master
ldd /root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master | grep -F "libcamera.so.0.7"
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master | grep -F "libcamera-base.so.0.7"
```

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

```bash
sudo su -
root-rw
apt update
apt dist-upgrade -y
MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise upgrade txing-unit-daemon txing-unit-kvs-master txing-unit-hardware-worker
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master --version
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker --version
ldd /root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master | grep -F "libcamera.so.0.7"
ldd /root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master | grep -F "libcamera-base.so.0.7"
sync
reboot
```

Boards upgraded from the pre-unit target naming must also remove the retired
systemd units during a writable-root maintenance window. After installing the
new `txing-unit.target` units and before rebooting:

```bash
systemctl disable --now txing-board.target txing-board-kvs-master.service || true
rm -f /etc/systemd/system/txing-board.target
rm -f /etc/systemd/system/txing-board-kvs-master.service
systemctl daemon-reload
```

## Local Development

Go unit daemon:

```bash
just unit::daemon::run
```

The local daemon uses
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}`.
Provision that directory with `just aws::cert <thing-id>` only when AWS
resource changes are intended.

Daemon and native board worker commands:

```bash
just unit::daemon::test
just unit::daemon::run
just unit::daemon::kvs-build-native
just unit::daemon::kvs-test-native
just unit::daemon::kvs-build-trixie
just unit::daemon::hardware-build-native
just unit::daemon::hardware-test-native
just unit::daemon::hardware-build-trixie
```

`kvs-build-native` builds `txing-unit-kvs-master` and lets the worker CMake
project fetch the pinned AWS KVS WebRTC SDK into the local build directory. It
enables the BoardVideoBridge gRPC client on Linux. Third-party KVS, protobuf,
and gRPC dependencies come from distro packages, not from the SDK's bundled
source builds.

Direct raw motor bring-up is no longer supported. Live motion testing goes
through the Go daemon MCP `cmd_vel` path, including the active-control lease
gate, with the hardware worker applying accepted commands locally.

## References

- [Artifacts](../artifacts.md)
- [Installation overview](../installation.md)
- [Unit board video contract](../../devices/unit/docs/board-video.md)
- [Board video bridge contract](../contracts/board-video-bridge.md)
- [Unit hardware worker contract](../contracts/unit-hardware-worker.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)
- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
