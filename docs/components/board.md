# Board

The board is the device-side Raspberry Pi. It is power-switched by the MCU,
runs the root-owned Rust `txing-unit-daemon`, supervises the native
`txing-board-kvs-master` process, publishes board-owned runtime state, and
exposes board MCP for motion control.

## Responsibilities

- publish the `board` named shadow
- publish the `video` named shadow mirror
- publish retained video descriptor/status topics under
  `txings/<device_id>/video/*`
- publish retained MCP descriptor/status topics under
  `txings/<device_id>/mcp/*`
- publish retained v2 capability state for `board`, `mcp`, and `video`
- supervise the native KVS WebRTC worker as a child process
- inject IoT role-alias temporary credentials into the native worker
- subscribe to Sparkplug `DCMD.redcon` and halt locally on `redcon=4`
- enforce MCP active-control ownership for actuator tools
- stop motors on command silence, active-control expiry, session close,
  transport switch, REDCON `4`, and daemon shutdown

## REDCON Contract

For the current `unit` device type:

- `REDCON 4`: BLE is reachable and the unit is in the sleep state.
- `REDCON 3`: BLE is reachable and MCU-controlled wakeup power/D1 is enabled.
- `REDCON 2`: board and MCP are available; video is unavailable or not ready.
- `REDCON 1`: board, MCP, and video are available.

The board publishes retained v2 capability state for `board`, `mcp`, and
`video`. `txing-sparkplug-manager` consumes that retained state directly for
REDCON projection. When BLE confirms REDCON `4` / `power=false`, Sparkplug
projection clears board-owned capabilities and does not reuse stale retained
board state on the next wake; fresh board daemon state must arrive before
`board`, `mcp`, or `video` become available again.

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
- stale `power=true` or `wifi.online=true` must not be treated as
  authoritative after a hard power cut.

### Video

Current video is headless AWS Kinesis Video Streams WebRTC:

- signaling channel: `<device_id>-board-video`
- browser route: `/<town>/<rig>/<device>/video`
- retained topics:
  - `txings/<device_id>/video/descriptor`
  - `txings/<device_id>/video/status`
- named shadow mirror: `video`
- worker binary: `txing-board-kvs-master`

The native worker owns camera capture, H.264 encode, AWS KVS master behavior,
WebRTC peer connections, and data-channel forwarding. The Rust daemon owns
worker supervision, readiness interpretation, retained state publication, MCP
business logic, and motor authority.

By default the daemon asks the native worker to use KVS dual-stack endpoints
and IPv6-preferred TURN behavior. `TXING_KVS_DISABLE_IPV4_TURN=true` is a
validation override, not the normal runtime setting.

The daemon parses native worker markers:

- `TXING_KVS_READY`
- `TXING_VIEWER_CONNECTED`
- `TXING_VIEWER_DISCONNECTED`
- `TXING_KVS_ERROR`
- MCP data-channel lifecycle markers

The board video contract is documented in
[devices/unit/docs/board-video.md](../../devices/unit/docs/board-video.md).

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

`daemon.env` is sourceable and rendered from
`devices/unit/daemon/daemon.env.template`. Certificate paths are omitted by
default; the daemon derives colocated paths from the loaded `daemon.env`
directory.

Default runtime inputs include:

- `AWS_REGION`
- `TXING_CAPABILITIES`
- `TXING_KVS_MASTER_COMMAND`
- `TXING_BOARD_VIDEO_CHANNEL_NAME`
- `TXING_MCP_WEBRTC_SOCKET_PATH`
- `TXING_KVS_PREFER_IPV6`
- `TXING_KVS_DISABLE_IPV4_TURN`
- `TXING_MOTOR_*`
- CloudWatch log configuration

The default video channel is `<thing_id>-board-video`. The default MCP WebRTC
IPC socket path is `/run/txing-unit-daemon/mcp-webrtc.sock`.
Existing boards with an older generated `daemon.env` must update
`TXING_MCP_WEBRTC_SOCKET_PATH`; generated config files are not overwritten by
binary upgrades.

## Release Artifacts

Boards install two GitHub Release assets through root-owned `mise`:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
```

Each archive contains one root-level executable:

```text
txing-unit-daemon
txing-board-kvs-master
```

Boards use root's persistent mise config and install tree:

```text
/root/.config/mise/conf.d/txing-unit-daemon.toml
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon
/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master
/root/.local/share/mise/installs/txing-unit-daemon/
/root/.local/share/mise/installs/txing-board-kvs-master/
```

Service starts are offline by design. Restarting
`txing-unit-daemon.service` does not install or upgrade tools. If a board needs
new binaries, log into the board, enter a root shell, switch root to writable
mode, run root-owned `mise upgrade`, and reboot.

## Fresh Board Install

Assumptions:

- Raspberry Pi Zero 2 W
- Raspberry Pi OS Lite 64-bit, Trixie
- `NetworkManager` manages networking
- AWS resources and the target unit thing already exist
- daemon config/certificate archive has been generated on the operator machine

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
txing-board-kvs-master = "github:mparkachov/txing"

[tools.txing-unit-daemon]
version = "latest"
asset_pattern = "txing-unit-daemon-linux-aarch64.tar.gz"

[tools.txing-board-kvs-master]
version = "latest"
asset_pattern = "txing-board-kvs-master-linux-aarch64.tar.gz"
EOF

MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise install txing-unit-daemon@latest txing-board-kvs-master@latest
```

Check the resolved binaries before writing the service:

```bash
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master --version
ldd /root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon
ldd /root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master
ldd /root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master | grep -F "libcamera.so.0.7"
ldd /root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master | grep -F "libcamera-base.so.0.7"
```

Write the root-owned systemd unit:

```bash
cat >/etc/systemd/system/txing-unit-daemon.service <<'EOF'
[Unit]
Description=Txing Unit Daemon
Wants=network-online.target systemd-time-wait-sync.service
After=network-online.target systemd-time-wait-sync.service time-sync.target
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
Environment=TXING_KVS_MASTER_COMMAND=/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master

ExecStartPre=/usr/bin/test -x /root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon
ExecStartPre=/usr/bin/test -x /root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master
ExecStartPre=-/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
ExecStartPre=-/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master --version
ExecStart=/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon

[Install]
WantedBy=multi-user.target
EOF

if systemctl list-unit-files NetworkManager-wait-online.service --no-legend --no-pager 2>/dev/null \
  | grep -q '^NetworkManager-wait-online\.service[[:space:]]'; then
  systemctl enable NetworkManager-wait-online.service
fi
systemctl daemon-reload
systemctl enable txing-unit-daemon.service
systemctl restart txing-unit-daemon.service
```

Verify:

```bash
systemctl status --no-pager -l txing-unit-daemon.service
journalctl -u txing-unit-daemon.service -n 160 --no-pager
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master --version
```

Expected:

- the daemon log includes `version=<release-version>`
- MQTT connects
- retained `board`, dynamic `mcp`, and `video` state is published
- the KVS master child reaches `TXING_KVS_READY` when camera and signaling are
  available
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

Useful root shell aliases:

```bash
cat >> "$HOME/.bashrc" <<'EOF'
alias root-ro='bash -c "rm -rf /var/tmp/* /tmp/* ; sync ; mount -o remount,ro /boot/firmware ; mount -o remount,ro / ; mount /tmp ; mount /var/tmp"'
alias root-rw='bash -c "mount -o remount,rw /; mount -o remount,rw /boot/firmware; umount /var/tmp /tmp; systemctl daemon-reload"'
EOF
```

Operational rules:

- do package installs, `mise` installs/updates, daemon config changes, and
  systemd unit changes while root is writable
- switch back to read-only only after runtime, native KVS master, and config
  files are in place
- the service runs as root with `HOME=/root`
- AWS-backed services must wait for network-online and clock synchronization so
  TLS validation does not race NTP

### 8. Final Reboot Check

```bash
root-ro
reboot
```

After reconnecting:

```bash
systemctl status --no-pager -l txing-unit-daemon.service
journalctl -u txing-unit-daemon.service -b -u txing-unit-daemon.service --no-pager
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master --version
```

Expected:

- root filesystem is read-only
- `txing-unit-daemon.service` starts without a source checkout
- service start logs daemon and KVS master versions
- daemon log includes `version=<release-version>`
- MQTT connects and retained board/MCP/video state is published

## Maintenance

Board update during a writable-root maintenance window:

```bash
sudo su -
root-rw
apt update
apt dist-upgrade -y
MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise upgrade txing-unit-daemon txing-board-kvs-master
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon --version
/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master --version
ldd /root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master | grep -F "libcamera.so.0.7"
ldd /root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master | grep -F "libcamera-base.so.0.7"
sync
reboot
```

## Local Development

Rust unit daemon:

```bash
just unit::daemon::run
```

The local daemon uses
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}`.
Provision that directory with `just aws::cert <thing-id>` only when AWS
resource changes are intended.

Daemon and native KVS worker commands:

```bash
just unit::daemon::test
just unit::daemon::run
just unit::daemon::kvs-submodules
just unit::daemon::kvs-build-native
just unit::daemon::kvs-test-native
```

`kvs-build-native` builds `txing-board-kvs-master` against the shared AWS KVS
WebRTC SDK submodule under `devices/common/board/`. Initialize it with
`just unit::daemon::kvs-submodules` before the first native build. Third-party
KVS dependencies come from distro packages, not from the SDK's bundled source
builds.

Direct raw motor bring-up is no longer supported. Live motion testing goes
through the Rust daemon MCP `cmd_vel` path, including the active-control lease
gate.

## References

- [Artifacts](../artifacts.md)
- [Installation overview](../installation.md)
- [Unit board video contract](../../devices/unit/docs/board-video.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)
- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
