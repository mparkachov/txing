# Board

The board is the device-side Raspberry Pi. It is power-switched by the MCU, runs
the root-owned Go daemon plus the native KVS master and hardware worker under
OpenRC, publishes board-owned runtime state, and exposes board MCP for motion
control.

One implementation serves every board device type. The daemon, KVS master, and
hardware worker are built once from `devices/common/board/`, with the device type
supplied as a build input that selects the binary names, the hardware socket
path, and the release stream. This runbook therefore covers every device type;
`<device>` below stands for the device type you are working on.

Boards run Alpine Linux with OpenRC. Debian receives no further investment and a
Debian board is reimaged rather than upgraded, per
[Board OS: Alpine only, Debian frozen](../constraints/board-os-alpine-only.md).
The superseded Debian and systemd steps are kept in
[Board (Debian, frozen)](./board-debian-frozen.md) for boards not yet reimaged.

## Device Types

Every value that differs between device types is listed here. Nothing else in
this document is device-specific.

| Value | `unit` | `cyberbrick` |
| --- | --- | --- |
| Daemon binary | `txing-unit-daemon` | `txing-cyberbrick-daemon` |
| KVS master binary | `txing-unit-kvs-master` | `txing-cyberbrick-kvs-master` |
| Hardware worker binary | `txing-unit-hardware-worker` | `txing-cyberbrick-hardware-worker` |
| Daemon config directory | `/root/.config/txing/unit-daemon` | `/root/.config/txing/cyberbrick-daemon` |
| Hardware worker socket | `/run/txing-unit-hardware-worker/unit-hardware.sock` | `/run/txing-cyberbrick-hardware-worker/cyberbrick-hardware.sock` |
| MCP adapter id | `dev.txing.unit.Daemon` | `dev.txing.cyberbrick.Daemon` |
| Release version file | `release/versions/unit` | `release/versions/cyberbrick` |
| Release tag prefix | `unit-v` | `cyberbrick-v` |
| Device manifest | `devices/unit/manifest.toml` | `devices/cyberbrick/manifest.toml` |
| Shadow schemas and defaults | `devices/unit/aws/` | `devices/cyberbrick/aws/` |

The daemon derives every one of these from the device type injected at build
time, so they are consequences of the profile rather than independent settings.
A board never mixes them: all three binaries on a board come from the same
device's release stream.

Operator commands are device-owned, matching the MCU commands:

```sh
just <device>::board::docker-build      # for example: just unit::board::docker-build
just <device>::board::docker-smoke
just <device>::board::hardware-test-native
```

Board operations that do not depend on the device type stay common-owned, the
same way `just mcu::check` is the shared MCU preflight:

```sh
just common::board::proto-gen           # regenerate the daemon's gRPC bindings
```

## Local Protocol Contracts

The daemon, KVS master, and hardware worker talk to each other over local unix
sockets using two device-independent gRPC packages, defined once in
`devices/common/board/proto/txing/board/`:

- `txing.board.board_video.v1.BoardVideoBridge` — the daemon serves it; the KVS
  master calls it for worker config, credentials, video state, and MCP
  forwarding. Contract: [Board video bridge](../contracts/board-video-bridge.md).
- `txing.board.hardware.v1.BoardHardware` — the hardware worker serves it; the
  daemon calls it for actuator readiness, `cmd_vel`, and stop requests.
  Contract: [Hardware worker](../contracts/unit-hardware-worker.md).

Neither package carries a device name, so the same binaries speak the same
contracts on every device type. The three binaries upgrade as a set; see
[Maintenance](#maintenance) for why a partial upgrade is the worst failure this
board has.

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

The ladder is declared per device type in `devices/<device>/manifest.toml`.
For both current board device types:

- `REDCON 4`: BLE GATT is confirmed commandable and the device is in the sleep state.
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
- worker binary: `txing-<device>-kvs-master`

The native worker owns camera capture, H.264 encode, AWS KVS master behavior,
WebRTC peer connections, and data-channel transport. The Go daemon owns
worker configuration, KVS temporary credentials, readiness interpretation,
retained state publication, MCP business logic, and actuator policy.

The daemon and native worker communicate through the local
BoardVideoBridge gRPC contract:
[docs/contracts/board-video-bridge.md](../contracts/board-video-bridge.md).
The proto source is
`txing.board.board_video.v1`.

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
The root-owned `txing-<device>-hardware-worker` owns motor hardware devices,
calibration, differential tank mixing, PWM/GPIO output, local hardware
readiness, and motor neutralization.

The daemon is a gRPC client and the worker is a gRPC server on the local Unix
domain socket:

```text
/run/txing-<device>-hardware-worker/<device>-hardware.sock
```

The worker API is `txing.board.hardware.v1.BoardHardware`:

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
/root/.config/txing/<device>-daemon/daemon.env
/root/.config/txing/<device>-daemon/AmazonRootCA1.pem
/root/.config/txing/<device>-daemon/certificate.arn
/root/.config/txing/<device>-daemon/certificate.pem.crt
/root/.config/txing/<device>-daemon/private.pem.key
/root/.config/txing/<device>-daemon/public.pem.key
```

`daemon.env` is a systemd-compatible environment file rendered from
`devices/common/board/daemon/daemon.env.template`. It uses plain `KEY=value` lines so
both `txing-<device>-hardware-worker.service` and the daemon can consume the same
root-owned file. Certificate paths are omitted by default; the daemon derives
colocated paths from the loaded `daemon.env` directory. For manual shell export,
use `set -a; . /root/.config/txing/<device>-daemon/daemon.env; set +a`.

Default runtime inputs include:

- `AWS_REGION`
- `TXING_DAEMON_CAPABILITIES`
- `TXING_BOARD_VIDEO_CHANNEL_NAME`
- `TXING_KVS_PREFER_IPV6`
- `TXING_KVS_DISABLE_IPV4_TURN`
- `TXING_HARDWARE_WORKER_TIMEOUT_MS`
- `TXING_MOTOR_*`
- CloudWatch log configuration

Local socket paths are deliberately not among them.
`TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH` and
`TXING_HARDWARE_WORKER_SOCKET_PATH` remain accepted as overrides, but the
generated `daemon.env` does not set them: each binary compiles
device-correct defaults and falls back to them when unset, so sockets follow
the installed binaries instead of the identity bundle. This keeps a bundle
generated for one device type from breaking another device's binaries, which
matters while boards run mixed combinations during the Debian-to-Alpine
transition.

Motor calibration supports per-track output trim through the shared
`daemon.env` file. Values are numeric percentages in `(0, 100]`; omit the `%`
sign. For example, if straight driving drifts left because the right track is
stronger, reduce the right side:

```text
TXING_MOTOR_LEFT_TRACK_POWER_PERCENT=100
TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT=98
```

Track power trim is board-local physical calibration. User-facing
`motion.leftSpeed` and `motion.rightSpeed` report the untrimmed logical
command. The worker maps that logical command into the configured raw motor
range, applies per-track trim, and keeps every nonzero physical output within
`TXING_MOTOR_CMD_RAW_MIN_SPEED` and `TXING_MOTOR_CMD_RAW_MAX_SPEED`.

The default video channel is `<thing_id>-board-video`. The default bridge
socket path is `/run/txing-<device>-daemon/board-video-bridge.sock` and the
default hardware worker socket is
`/run/txing-<device>-hardware-worker/<device>-hardware.sock`, both compiled into the
board binaries. Existing boards with an older generated `daemon.env` must
remove leading `export ` prefixes for systemd `EnvironmentFile=`
compatibility and add `TXING_HARDWARE_WORKER_TIMEOUT_MS`; generated config
files are not overwritten by binary upgrades. Older files that still carry
`TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH` or `TXING_HARDWARE_WORKER_SOCKET_PATH`
should have those lines deleted so the compiled defaults apply. Existing boards must also add
`TXING_MOTOR_LEFT_TRACK_POWER_PERCENT=100` and
`TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT=100` if their `daemon.env` predates
track power trim. The daemon ignores `TXING_MOTOR_*`; those values are consumed
by `txing-<device>-hardware-worker` when its OpenRC service loads the same root-owned
env file.
## OS And ABI Contract

- Alpine Linux aarch64 on Raspberry Pi Zero 2 W, **sys install**
  (`setup-disk -m sys`), device apk repositories on the Alpine `v3.24` branch.
- Default Alpine stack: apk, ifupdown-ng + wpa_supplicant + udhcpc
  networking, chronyd time sync, OpenRC init. No systemd and no
  NetworkManager on the board.
- The daemon and hardware worker are fully static musl binaries that depend
  only on the kernel: a healthy install shows no shared-library dependencies
  for them (musl `ldd` refuses them or lists only the loader).
- The KVS master is the only musl-dynamic binary: it shows the
  `/lib/ld-musl-aarch64.so.1` interpreter, fully resolved `ldd` output, and
  links Alpine's upstream libcamera (`libcamera.so.0.7` and
  `libcamera-base.so.0.7`). If its `ldd` reports `not found` libraries or a
  non-musl interpreter, the release asset was built for the wrong OS or the
  wrong Alpine branch and must be replaced.
- Linking the KVS master against libcamera is necessary but not sufficient for
  video. Camera capture additionally requires the Raspberry Pi pipeline
  handler, IPA module, and sensor tuning files (`libcamera-raspberrypi`), a
  running udev daemon for libcamera's device enumerator (`eudev`), firmware
  camera autodetection in `config.txt`, and the `bcm2835-codec` and
  `bcm2835-isp` kernel modules. None of these are implied by the build
  container's package set or by `ldd` linkage checks, and every one of them
  fails as the same KVS master error,
  `configured camera index is not available`. See
  [Install OS Packages](#2-install-os-packages),
  [Enable Udev](#2a-enable-udev), and
  [Enable PWM Overlay And Camera](#6-enable-pwm-overlay-and-camera).
- The KVS master verifies the AWS signaling endpoint against a single trust
  anchor and cannot use Alpine's full `/etc/ssl/certs/ca-certificates.crt`
  bundle: the SDK's TLS layer follows the server-presented chain and a
  140-cert bundle fails (`X509_V_ERR = 20`) where the one Starfield Services
  Root CA G2 that AWS chains to succeeds. The daemon config bundle ships that
  anchor as `SFSRootCAG2.pem` alongside `AmazonRootCA1.pem`, and the KVS
  service points the binary at it through `TXING_KVS_SYSTEM_CA_CERT_PATH`. The
  daemon's own MQTT TLS is separate and uses `AmazonRootCA1.pem`.
- The pinned Alpine build image in the board daemon justfile, the
  release workflow containers, and the on-device apk branch must name the
  same Alpine release. Bumping the Alpine release is one coordinated change
  across all three plus a new board release; see
  [Maintenance](#maintenance).

## Release Artifacts

Boards install three GitHub Release assets from the immutable
`<device>-v*` release stream through root-owned `mise`:

```text
txing-<device>-daemon-linux-aarch64.tar.gz
txing-<device>-kvs-master-linux-aarch64.tar.gz
txing-<device>-hardware-worker-linux-aarch64.tar.gz
```

Each archive contains one root-level executable with the same command name.
Boards use root's persistent mise config and install tree:

```text
/root/.config/mise/conf.d/txing-<device>-daemon.toml
/root/.local/share/mise/installs/txing-<device>-daemon/latest/txing-<device>-daemon
/root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master
/root/.local/share/mise/installs/txing-<device>-hardware-worker/latest/txing-<device>-hardware-worker
```

Root-owned `mise` configs must set `version_prefix = "<device>-v"` so
`latest` resolves from `<device>-v*` GitHub Releases instead of the
repository-wide latest release. This release model is forward-only;
replace old board configs manually if they do not include the component prefix. Service starts are offline by design:
restarting an OpenRC service does not install or upgrade tools, invoke mise,
or call GitHub. If a board needs new binaries, follow
[Maintenance](#maintenance).

The release gates bound what these artifacts prove. `assert-board-musl.sh`
checks linkage kinds and `smoke-board-cross-distro.sh` runs each binary in
`debian:trixie` and pinned Alpine containers asserting only `--version`.
Neither performs a live AWS handshake (no credentials in CI) nor touches a
camera, and the smoke container installs the same build-derived package set
that omits `libcamera-raspberrypi` and a udev daemon. TLS trust-anchor faults
and every camera-enumeration fault in
[Camera Does Not Enumerate](#camera-does-not-enumerate) are therefore
invisible to CI by construction and can only be caught on a physical board
with a camera attached.

## Fresh Board Install

Assumptions:

- Raspberry Pi Zero 2 W
- Alpine Linux aarch64 Raspberry Pi image from the `v3.24` branch
- AWS resources and the target thing already exist
  (`just aws::deploy` once per stack, then
  `just aws::deploy-device <raspi-rig-id> <device> <name>`)
- daemon environment/certificate archive has been generated on the operator
  machine

### 1. Create The Card And Sys Install

Prepare the SD card on the operator machine with the Alpine `v3.24`
Raspberry Pi aarch64 image (`alpine-rpi-<version>-aarch64`) following the
Alpine Raspberry Pi imaging instructions, boot the board from it, and log in
on the console as `root` (empty password).

Run the interactive base setup:

```sh
setup-alpine
```

Answers that matter for a board:

- hostname: any stable name; board identity is the thing id carried in the
  daemon config, the hostname is cosmetic
- interface: `wlan0` with the deployment Wi-Fi SSID and passphrase
  (setup-alpine configures ifupdown-ng + wpa_supplicant + udhcpc), or `eth0`
  with a wired adapter
- NTP client: `chronyd` (the default)
- SSH server: `openssh`, with the operator public key installed for `root` so
  the remaining steps can run over SSH
- disk mode: `none` (the sys install target partition is created next)

The Raspberry Pi image boots diskless from the FAT partition. Convert the
same card to a persistent sys install:

```sh
apk add cfdisk e2fsprogs
cfdisk /dev/mmcblk0
setup-disk -m sys /dev/mmcblk0p2
```

In `cfdisk`, create one Linux partition (`/dev/mmcblk0p2`) in the free space
after the boot FAT partition and write the table before quitting. After
`setup-disk` finishes, point the boot FAT at the new root filesystem if
`setup-disk` did not already do it, then reboot into the sys install:

```sh
mount -o remount,rw /media/mmcblk0p1
grep -q 'root=/dev/mmcblk0p2' /media/mmcblk0p1/cmdline.txt \
  || sed -i 's|$| root=/dev/mmcblk0p2|' /media/mmcblk0p1/cmdline.txt
reboot
```

All remaining steps run as `root` on the sys install while the root
filesystem is still writable. `setup-disk -m sys` writes a UUID-based
`/etc/fstab` and mounts the boot FAT at `/boot` (not `/media/mmcblk0p1`, which
only existed during the diskless boot above); steps 6 and 7 use `/boot` and
those UUIDs.

### 2. Install OS Packages

`setup-alpine` enables only the `main` apk repository, but libcamera, grpc,
and re2 ship in `community`; uncomment it first:

```sh
sed -i 's|^#\(http.*/community\)$|\1|' /etc/apk/repositories
apk update
apk upgrade
apk add \
  curl jq ca-certificates \
  curl-dev openssl-dev log4cplus-dev libsrtp-dev libusrsctp-dev \
  libwebsockets-dev zlib-dev libcamera-dev \
  protobuf-dev grpc-dev \
  libcamera-raspberrypi eudev v4l-utils
```

The dev packages are the proven runtime superset from the pinned Alpine build
container: installing them guarantees every shared library the musl-dynamic
release KVS master resolves at run time, on the same `v3.24` branch the
release was built against (the static daemon and hardware worker need none of
them). The manual install checks below run `ldd` on the resolved
binaries before the services are enabled. The release KVS master must link
`libcamera.so.0.7` and `libcamera-base.so.0.7` from Alpine `v3.24`; if the
sonames do not resolve, the installed apk branch and the release were built
against different Alpine releases and must be realigned first.

`libcamera-raspberrypi` and `eudev` are **runtime-only** requirements that the
build-container package set does not imply, and neither is pulled in as a
dependency of anything above:

- `libcamera-dev` provides only what the KVS master links against
  (`libcamera.so.0.7`, `libcamera-base.so.0.7`). The Raspberry Pi pipeline
  handler, the `ipa_rpi_vc4.so` IPA module, and the per-sensor tuning files in
  `/usr/share/libcamera/ipa/rpi/vc4/` live in `libcamera-raspberrypi`. Without
  it libcamera starts normally and enumerates zero cameras.
- libcamera links `libudev.so.1` and therefore uses its **udev** device
  enumerator, not the sysfs fallback. apk satisfies `so:libudev.so.1` with
  `eudev-libs` alone, which is the shared library and not the daemon; with no
  udev running, libcamera queries an empty database and again enumerates zero
  cameras while `/dev/media0` works normally. `eudev` supplies the daemon,
  wired into the `sysinit` runlevel in
  [Enable Udev](#2a-enable-udev).

Both failures surface identically and misleadingly, as
`configured camera index is not available` from the KVS master — the error the
capturer raises when the requested camera index exceeds the enumerated camera
count, which is `0`. `v4l-utils` is not required at run time; it provides
`media-ctl` for the diagnostics in
[Camera Does Not Enumerate](#camera-does-not-enumerate).

### 2a. Enable Udev

Alpine's `setup-alpine` leaves the board on busybox `mdev`. libcamera needs a
udev database, so switch device management to udev before installing the
runtime. `setup-udev` from `alpine-conf` is not present on all Alpine images;
wire the services directly, which is equivalent and image-independent:

```sh
for s in udev udev-trigger udev-settle; do rc-update add $s sysinit; done
rc-service udev start
rc-service udev-trigger start
```

Verify:

```sh
ls -d /run/udev
rc-status sysinit | grep -i udev
```

The three services must land in **`sysinit`**, not `default`: device
enumeration has to complete before the txing services start, and `sysinit`
placement is also what makes this survive the read-only-root reboot in
[Configure Read-Only Root](#7-configure-read-only-root). A board where video
works before a reboot and fails after it is almost always udev left in the
wrong runlevel.

### 3. Install Mise

`mise` ships as a static musl binary and installs on Alpine unchanged:

```sh
mkdir -p "$HOME/.local/bin"
curl https://mise.run | sh
if ! grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.profile" 2>/dev/null; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile"
fi
/root/.local/bin/mise --version
```

### 4. Generate And Copy Daemon Config

On the operator machine:

```sh
just aws::cert <thing-id>
scp certs/<thing-id>/<thing-id>-daemon-config.tgz root@<board-host>:/tmp/<thing-id>-daemon-config.tgz
```

On the board:

```sh
install -d -m 700 "$HOME/.config/txing/<device>-daemon"
tar --no-same-owner -xzf /tmp/<thing-id>-daemon-config.tgz -C "$HOME/.config/txing/<device>-daemon"
chmod 700 "$HOME/.config/txing/<device>-daemon"
chmod 600 "$HOME/.config/txing/<device>-daemon/daemon.env"
chmod 600 "$HOME/.config/txing/<device>-daemon/certificate.arn"
chmod 600 "$HOME/.config/txing/<device>-daemon/certificate.pem.crt"
chmod 600 "$HOME/.config/txing/<device>-daemon/private.pem.key"
chmod 600 "$HOME/.config/txing/<device>-daemon/public.pem.key"
chmod 644 "$HOME/.config/txing/<device>-daemon/AmazonRootCA1.pem"
chmod 644 "$HOME/.config/txing/<device>-daemon/SFSRootCAG2.pem"
rm -f /tmp/<thing-id>-daemon-config.tgz
```

`AmazonRootCA1.pem` is the daemon's MQTT trust root; `SFSRootCAG2.pem` is the
Starfield Services Root CA G2 that the KVS master's signaling TLS verifies
against (see [OS And ABI Contract](#os-and-abi-contract)). Both are fetched
from AWS's public repository by `just aws::cert` and shipped in the bundle.

`daemon.env` is rendered from
`devices/common/board/daemon/daemon.env.template` and uses plain `KEY=value`
lines so both the daemon and the hardware worker init script can consume the
same root-owned file. Certificate paths are omitted by default; the daemon
derives colocated paths from the loaded `daemon.env` directory. For manual
shell export, use
`set -a; . /root/.config/txing/<device>-daemon/daemon.env; set +a`.
Motor calibration, including
`TXING_MOTOR_LEFT_TRACK_POWER_PERCENT`/`TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT`
track trim, follows the board contract above.

If the device daemon role policy needs to be refreshed later (for example
after policy changes on the operator side), run this on the operator machine:

```sh
just <device>::board::role-policy <thing-id>
```

### 5. Install Runtime And OpenRC Services

Install the release tools through root-owned `mise`.
`minimum_release_age = "0s"` opts out of mise's default 24-hour release-age
filter: boards install first-party releases minutes after they are
published, and with the default filter `latest` resolves to nothing.

```sh
install -d -m 700 /root/.config/mise/conf.d /root/.local/share/mise
cat >/root/.config/mise/conf.d/txing-<device>-daemon.toml <<'EOF'
[settings]
fetch_remote_versions_cache = "10m"
minimum_release_age = "0s"

[tool_alias]
txing-<device>-daemon = "github:mparkachov/txing"
txing-<device>-kvs-master = "github:mparkachov/txing"
txing-<device>-hardware-worker = "github:mparkachov/txing"

[tools.txing-<device>-daemon]
version = "latest"
version_prefix = "<device>-v"
asset_pattern = "txing-<device>-daemon-linux-aarch64.tar.gz"

[tools.txing-<device>-kvs-master]
version = "latest"
version_prefix = "<device>-v"
asset_pattern = "txing-<device>-kvs-master-linux-aarch64.tar.gz"

[tools.txing-<device>-hardware-worker]
version = "latest"
version_prefix = "<device>-v"
asset_pattern = "txing-<device>-hardware-worker-linux-aarch64.tar.gz"
EOF

MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise install txing-<device>-daemon@latest txing-<device>-kvs-master@latest txing-<device>-hardware-worker@latest
```

Check the resolved binaries before writing the services. Every binary must
report the release version; the static daemon and hardware worker must show
no shared-library dependencies (musl `ldd` refuses them or lists only the
loader), and the musl-dynamic KVS master must use the musl interpreter and
resolve all shared libraries:

```sh
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-<device>-daemon/latest/txing-<device>-daemon --version
/root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master --version
/root/.local/share/mise/installs/txing-<device>-hardware-worker/latest/txing-<device>-hardware-worker --version
ldd /root/.local/share/mise/installs/txing-<device>-daemon/latest/txing-<device>-daemon || true
ldd /root/.local/share/mise/installs/txing-<device>-hardware-worker/latest/txing-<device>-hardware-worker || true
ldd /root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master
ldd /root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master | grep -F "libcamera.so.0.7"
ldd /root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master | grep -F "libcamera-base.so.0.7"
```

Confirm the KVS signaling anchor provisioned with the daemon config is
present and names the expected root:

```sh
openssl x509 -in /root/.config/txing/<device>-daemon/SFSRootCAG2.pem -noout -subject
```

The subject must name `Starfield Services Root Certificate Authority - G2`.
The KVS service points its TLS at this file through
`TXING_KVS_SYSTEM_CA_CERT_PATH` (set in the init script below), because the
SDK cannot verify the signaling chain against the full OS bundle. This anchor
is stable (valid to 2037).

Write the root-owned OpenRC init scripts. There is no OpenRC equivalent of
unit's `txing-unit.target`; each service is enabled individually and OpenRC
dependencies order them hardware worker, then daemon, then KVS master. The
daemon owns the board-video bridge socket; the KVS master connects to it as a
separate service. The hardware worker owns the BoardHardware socket; the
daemon connects to it as a client and degrades if it is unavailable. All
three services run under `supervise-daemon`, which restarts them on failure
with bounded respawn limits. The daemons exit cleanly on the default
supervise-daemon stop signal.

```sh
cat >/etc/init.d/txing-<device>-hardware-worker <<'EOF'
#!/sbin/openrc-run

description="Txing Board Hardware Worker"

supervisor=supervise-daemon
command=/root/.local/share/mise/installs/txing-<device>-hardware-worker/latest/txing-<device>-hardware-worker
directory=/root
respawn_delay=2
respawn_max=5
respawn_period=600
output_log=/var/log/txing-<device>-hardware-worker.log
error_log=/var/log/txing-<device>-hardware-worker.log

daemon_env=/root/.config/txing/<device>-daemon/daemon.env

depend() {
    need localmount
    before txing-<device>-daemon
}

start_pre() {
    test -x "$command" || return 1
    test -r "$daemon_env" || return 1
    checkpath --directory --mode 0755 --owner root:root /run/txing-<device>-hardware-worker
    set -a
    . "$daemon_env"
    set +a
    export HOME=/root
}
EOF

cat >/etc/init.d/txing-<device>-daemon <<'EOF'
#!/sbin/openrc-run

description="Txing Board Daemon"

supervisor=supervise-daemon
command=/root/.local/share/mise/installs/txing-<device>-daemon/latest/txing-<device>-daemon
directory=/root
respawn_delay=5
respawn_max=5
respawn_period=600
output_log=/var/log/txing-<device>-daemon.log
error_log=/var/log/txing-<device>-daemon.log

depend() {
    need net
    use dns chronyd
    after txing-<device>-hardware-worker
}

start_pre() {
    test -x "$command" || return 1
    checkpath --directory --mode 0755 --owner root:root /run/txing-<device>-daemon
    if ! chronyc waitsync 60 0 0 3 >/dev/null 2>&1; then
        ewarn "clock is not confirmed synchronized; AWS TLS setup may retry"
    fi
    export HOME=/root
    export TXING_DAEMON_CONFIG_DIR=/root/.config/txing/<device>-daemon
}
EOF

cat >/etc/init.d/txing-<device>-kvs-master <<'EOF'
#!/sbin/openrc-run

description="Txing Board KVS Master"

supervisor=supervise-daemon
command=/root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master
directory=/root
respawn_delay=5
respawn_max=5
respawn_period=600
output_log=/var/log/txing-<device>-kvs-master.log
error_log=/var/log/txing-<device>-kvs-master.log

ca_cert=/root/.config/txing/<device>-daemon/SFSRootCAG2.pem

depend() {
    need net
    use dns
    after txing-<device>-daemon
}

start_pre() {
    test -x "$command" || return 1
    test -r "$ca_cert" || return 1
    export HOME=/root
    export TXING_KVS_SYSTEM_CA_CERT_PATH="$ca_cert"
    export TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH=/run/txing-<device>-daemon/board-video-bridge.sock
}
EOF

chmod 755 /etc/init.d/txing-<device>-hardware-worker
chmod 755 /etc/init.d/txing-<device>-daemon
chmod 755 /etc/init.d/txing-<device>-kvs-master

rc-update add txing-<device>-hardware-worker default
rc-update add txing-<device>-daemon default
rc-update add txing-<device>-kvs-master default
rc-service txing-<device>-hardware-worker restart
rc-service txing-<device>-daemon restart
rc-service txing-<device>-kvs-master restart
```

Verify:

```sh
rc-status default
rc-service txing-<device>-hardware-worker status
rc-service txing-<device>-daemon status
rc-service txing-<device>-kvs-master status
tail -n 160 /var/log/txing-<device>-hardware-worker.log
tail -n 160 /var/log/txing-<device>-daemon.log
tail -n 160 /var/log/txing-<device>-kvs-master.log
```

Expected:

- all three services are `started` and stay up under `supervise-daemon`
- the daemon's local OpenRC log
  (`/var/log/txing-<device>-daemon.log`) is empty by design: the Go daemon
  ships logs to CloudWatch (`txing/<town>/<rig>/<thing>`), not stdout. Confirm
  it locally by a stable single daemon PID that is not respawning and by the
  bound bridge socket; version, MQTT connect, and state publishes appear in
  CloudWatch
- the daemon binds `/run/txing-<device>-daemon/board-video-bridge.sock`
- the hardware worker binds
  `/run/txing-<device>-hardware-worker/<device>-hardware.sock`
- the worker logs version and local actuator readiness or a clear hardware
  error (a missing `/sys/class/pwm/pwmchip0` before the PWM overlay in
  [Enable PWM Overlay And Camera](#6-enable-pwm-overlay-and-camera) is
  expected)
- MQTT connects and retained `board`, dynamic `mcp`, and `video` state is
  published (visible in CloudWatch)
- the KVS master service reaches READY over the bridge when camera and
  signaling are available; with no camera attached it completes signaling and
  then exits on `configured camera index is not available` and
  supervise-daemon retires it to `failed` — expected until a camera is present
- REDCON can reach `1` after Sparkplug projection sees fresh `board`, `mcp`,
  and `video` capability state

### 6. Enable PWM Overlay And Camera

After `setup-disk -m sys`, the boot FAT partition is mounted at `/boot` (the
`/media/mmcblk0p1` mount only exists during the diskless boot in step 1). Add
the overlay while `/boot` is writable. If `config.txt` includes `usercfg.txt`,
append to `usercfg.txt`; otherwise append to `config.txt` directly:

```sh
grep -q 'pwm-2chan' /boot/config.txt /boot/usercfg.txt 2>/dev/null || {
  if grep -q 'include usercfg.txt' /boot/config.txt; then
    printf 'dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4\n' >> /boot/usercfg.txt
  else
    printf 'dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4\n' >> /boot/config.txt
  fi
}
```

The `pwm-2chan.dtbo` overlay ships in Alpine's `raspberrypi-bootloader`
content already present on the boot FAT partition. Reboot after changing the
overlay so `/sys/class/pwm/pwmchip0` exists; without it the hardware worker
logs `PWM chip path does not exist` on every start.

The camera is off by default and needs firmware autodetection plus two kernel
modules. Nothing in the base Alpine image enables either:

```sh
grep -q 'camera_auto_detect' /boot/config.txt /boot/usercfg.txt 2>/dev/null || {
  if grep -q 'include usercfg.txt' /boot/config.txt; then
    printf 'camera_auto_detect=1\n' >> /boot/usercfg.txt
  else
    printf 'camera_auto_detect=1\n' >> /boot/config.txt
  fi
}

for m in bcm2835-codec bcm2835-isp; do
  grep -qx "$m" /etc/modules || echo "$m" >> /etc/modules
done
```

`camera_auto_detect=1` makes the firmware probe the CSI sensor over I²C and
insert the matching overlay; without it no sensor, `unicam`, or `/dev/video0`
appears at all. A non-standard sensor needs an explicit `dtoverlay=` line
instead.

The two modules cover the rest of the pipeline and neither autoloads:

- `bcm2835-codec` registers the V4L2 H.264 encoder at `/dev/video11`, which
  the KVS master opens by that hard-coded path. Missing, the capturer fails
  with `failed to open V4L2 H.264 encoder` *after* the camera opens
  successfully.
- `bcm2835-isp` registers the ISP nodes (`/dev/video13`–`/dev/video16`,
  `/dev/video20`–`/dev/video23`) and its own media devices. libcamera's
  `rpi/vc4` pipeline handler needs an ISP media device in addition to Unicam,
  so without it enumeration returns zero cameras even when the sensor probes
  correctly.

Reboot after this step and confirm before continuing:

```sh
ls /dev/video* /dev/media*
for d in /sys/class/video4linux/*; do echo "$(basename $d) -> $(cat $d/name)"; done
dmesg | grep -iE 'imx|ov5647|unicam|codec'
```

Expect the sensor subdev named for the attached module (for example
`imx708_wide`), `unicam-image` on `/dev/video0`, `/dev/video11` present, and
four media devices: `unicam`, `bcm2835-codec`, and two `bcm2835-isp`.

### 7. Configure Read-Only Root

The runtime is compatible with read-only root as long as these paths stay
writable on tmpfs:

- `/tmp`
- `/var/tmp`
- `/var/log`
- `/var/lib/chrony`

The native KVS worker keeps the signaling cache in memory and does not depend
on the SDK default `.SignalingCache_v1` file. chronyd tolerates a missing
drift file on the `/var/lib/chrony` tmpfs; it only costs a warning at boot.

Make `/etc/resolv.conf` point at udhcpc's runtime resolver output before
switching root to read-only. With a regular file on read-only root, udhcpc
cannot refresh resolver configuration after boot and DNS may fail even when
the network is otherwise online:

```sh
echo 'RESOLV_CONF="/run/resolv.conf"' >> /etc/udhcpc/udhcpc.conf
rm -f /etc/resolv.conf
ln -s /run/resolv.conf /etc/resolv.conf
readlink /etc/resolv.conf
rc-service networking restart
getent hosts example.com
```

`setup-disk -m sys` writes a UUID-based fstab with the root ext4 at `/` and
the boot FAT at `/boot`. Read the two UUIDs from `blkid` (root is the ext4
partition, boot is the vfat partition) and set both to `ro`, adding the
tmpfs mounts:

```sh
blkid   # note the ext4 (root) and vfat (boot) UUIDs
```

```fstab
UUID=<root-ext4-uuid>  /      ext4  ro,noatime  0 1
UUID=<boot-vfat-uuid>  /boot  vfat  ro,noatime  0 2
tmpfs  /tmp             tmpfs  nosuid,nodev,mode=1777,size=32M      0 0
tmpfs  /var/tmp         tmpfs  nosuid,nodev,exec,mode=1777,size=96M 0 0
tmpfs  /var/log         tmpfs  nosuid,nodev,mode=0755,size=16M      0 0
tmpfs  /var/lib/chrony  tmpfs  nosuid,nodev,mode=0755,size=4M       0 0
```

The RPi firmware reads `config.txt`/`cmdline.txt` from the FAT before Linux
mounts it, so a read-only `/boot` does not affect boot; `root-rw` remounts it
writable for later overlay or kernel changes.

Useful shell aliases:

```sh
cat >> /root/.profile <<'EOF'
alias root-rw='mount -o remount,rw /; mount -o remount,rw /boot; umount /var/tmp 2>/dev/null; umount /tmp 2>/dev/null'
alias root-ro='rm -rf /var/tmp/* /tmp/* ; sync; mount -o remount,ro /boot ; mount -o remount,ro / ; mount /tmp ; mount /var/tmp'
EOF
```

Operational rules:

- do apk installs, `mise` installs/updates, daemon config changes, and
  OpenRC init script changes while root is writable
- switch back to read-only only after runtime binaries, native workers, and
  config files are in place
- the services run as root with `HOME=/root`
- AWS-backed services depend on net and wait for clock synchronization so TLS
  validation does not race NTP
- the hardware worker neutralizes motors internally; supervise-daemon restart
  latency is supervision only, not the motion-control safety layer

### 8. Final Reboot Check

```sh
root-ro
reboot
```

After reconnecting:

```sh
mount | grep ' / '
rc-status default
rc-service txing-<device>-hardware-worker status
rc-service txing-<device>-daemon status
rc-service txing-<device>-kvs-master status
tail -n 160 /var/log/txing-<device>-hardware-worker.log
tail -n 160 /var/log/txing-<device>-daemon.log
tail -n 160 /var/log/txing-<device>-kvs-master.log
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-<device>-daemon/latest/txing-<device>-daemon --version
/root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master --version
/root/.local/share/mise/installs/txing-<device>-hardware-worker/latest/txing-<device>-hardware-worker --version
readlink /etc/resolv.conf
getent hosts example.com
```

Expected:

- root filesystem is read-only
- `/etc/resolv.conf` points at `/run/resolv.conf` and DNS resolves through
  udhcpc
- the daemon and hardware worker start under OpenRC and stay up without a
  source checkout and without network access to GitHub; the KVS master also
  autostarts and completes signaling but stays up only with a camera attached
- the daemon reports version, MQTT connect, and retained board/MCP/video state
  to CloudWatch (its local OpenRC log is empty by design); confirm locally by a
  stable daemon PID and the bound bridge socket
- udev is in the `sysinit` runlevel and `/run/udev` exists after the reboot,
  so libcamera enumerates the camera on a cold boot and not only in the
  session where the modules were loaded by hand

With a camera attached, confirm the full video path end to end:

```sh
rc-service txing-<device>-kvs-master stop
/root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master \
  --camera-probe
rc-service txing-<device>-kvs-master start
grep -E 'TXING_KVS_READY|TXING_KVS_ERROR' /var/log/txing-<device>-kvs-master.log
```

`--camera-probe` is capture-only: it exercises camera enumeration, capture,
and H.264 encoding without opening a KVS session, which separates camera
faults from AWS faults. Under the service, `TXING_KVS_READY` is emitted on the
first encoded keyframe and is the same event that reports `READY` over the
bridge and raises the `video` capability; REDCON reaches `1` shortly after.

Motor movement on both PWM channels is the remaining first bring-up
confirmation. Record deviations as milestone findings instead of patching
around them.

## Troubleshooting

### Camera Does Not Enumerate

The KVS master reports `configured camera index is not available` whenever the
requested camera index is not below the enumerated camera count. With the
default index `0` this means libcamera enumerated **no** cameras, and it is
the single error for every distinct cause below. `ldd` linkage checks and
`--version` all pass in each case, so work down the pipeline in order:

```sh
ls /dev/video* /dev/media*
for d in /sys/class/video4linux/*; do echo "$(basename $d) -> $(cat $d/name)"; done
ls /usr/lib/libcamera/ipa/ | grep rpi
ls /usr/share/libcamera/ipa/rpi/vc4/ | head
ls -d /run/udev
rc-status sysinit | grep -i udev
LIBCAMERA_LOG_LEVELS=*:DEBUG \
  /root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master \
  --camera-probe 2>&1 | tail -40
```

| Symptom | Cause | Fix |
| --- | --- | --- |
| No `/dev/video0`, no sensor in `dmesg` | firmware camera autodetection off | `camera_auto_detect=1` ([step 6](#6-enable-pwm-overlay-and-camera)) |
| `/dev/video0` present, no `/dev/video11` | `bcm2835-codec` not loaded | add to `/etc/modules` ([step 6](#6-enable-pwm-overlay-and-camera)) |
| Only `unicam` + `bcm2835-codec` media devices | `bcm2835-isp` not loaded | add to `/etc/modules` ([step 6](#6-enable-pwm-overlay-and-camera)) |
| No `ipa_rpi_vc4.so`, no `vc4/` tuning dir | `libcamera-raspberrypi` missing | `apk add libcamera-raspberrypi` ([step 2](#2-install-os-packages)) |
| All of the above present, `/run/udev` missing | no udev daemon | `apk add eudev` + [step 2a](#2a-enable-udev) |

The debug trace is decisive. `Unable to acquire a Unicam instance` from
`rpi/vc4` means the pipeline handler ran but matched no Unicam media device —
either the ISP/tuning pieces are missing, or the enumerator itself is empty
because udev is not running. `Unable to acquire a CFE instance` from
`rpi/pisp` immediately above it is expected and harmless: that is the Pi 5
pipeline handler correctly declining a Pi Zero 2 W.

Confirm the media device layer independently of libcamera with `media-ctl`,
which reads the devices directly and does not use udev:

```sh
for m in /dev/media*; do echo "== $m"; media-ctl -d $m -p | head -8; done
```

A healthy Pi Zero 2 W shows four media devices — `unicam`, `bcm2835-codec`,
and two `bcm2835-isp`. If `media-ctl` shows a working `unicam` while
libcamera still enumerates nothing, the fault is in libcamera's enumeration
(udev or `libcamera-raspberrypi`), not in the kernel or the sensor.

### Video Never Reaches READY

If the KVS master logs repeated `GetWorkerConfig failed: ... connect failed`
against the bridge socket, the worker cannot reach the daemon and never gets
as far as the camera. The daemon binds the bridge socket at startup and only
when `video` is in `TXING_DAEMON_CAPABILITIES`:

```sh
grep -E 'CAPABILITIES|SOCKET_PATH' /root/.config/txing/<device>-daemon/daemon.env
ls -l /run/txing-<device>-daemon/ /run/txing-<device>-hardware-worker/
pid=$(pgrep -f txing-<device>-daemon | head -1)
tr '\0' '\n' < /proc/$pid/environ | grep SOCKET_PATH
```

An empty `/run/txing-<device>-daemon/` with a healthy daemon means `video`
is absent from the capability list, or the daemon bound a path other than the
one the KVS service dials. The same applies to the hardware worker: a daemon
logging `connect to hardware worker: context deadline exceeded` against a
bound worker socket means the two resolved different paths.

`daemon.env` deliberately does **not** set `TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH`
or `TXING_HARDWARE_WORKER_SOCKET_PATH`. Every binary compiles device-correct
defaults and falls back to them when unset, so sockets follow the installed
binaries. A `SOCKET_PATH` line in a board's `daemon.env` is therefore a
red flag: it usually means the file was generated before this default was
adopted, or was hand-edited. Remove the line and restart rather than
compensating elsewhere — in particular, do not pin these paths with `export`
in the OpenRC `start_pre()` blocks, which reintroduces by hand exactly the
per-device coupling the defaults remove.

The `/proc/<pid>/environ` read is the authoritative check: it shows what the
running daemon resolved, including anything an init script exported, rather
than what a config file claims.

Both failure modes are quiet by construction — the daemon logs to CloudWatch
rather than locally, so an empty `/var/log/txing-<device>-daemon.log` is
expected and is not evidence of either problem.

### Restart Order

Service restarts have a required order, dependencies first:

```sh
rc-service txing-<device>-hardware-worker restart
rc-service txing-<device>-daemon restart
rc-service txing-<device>-kvs-master restart
```

**Restarting the daemon always requires restarting the KVS master after it.**
A daemon restart resets its video state to `starting` and recreates the bridge
socket, but the KVS master emits `READY` only once per session, latched on the
first encoded keyframe. It keeps streaming to AWS while the daemon believes
video never came up, so the `video` capability stays false, REDCON falls back
to `2`, and MCP reports the WebRTC data channel as unavailable. State reporting
over the bridge is best-effort and logs nothing when it fails, so the only
symptom is video silently never becoming ready.

Restarting the hardware worker or the KVS master alone is safe and needs no
daemon restart: the daemon dials the worker per request and does not cache
failed connections. *Upgrading* one of them alone is not safe; see
[Maintenance](#maintenance).

## Maintenance

Board update during a writable-root maintenance window. Publish a new
immutable `<device>-vX.Y.Z` release first.

Upgrade the daemon, the hardware worker, and the KVS master together, in one
window, as the `mise upgrade` below does. They speak the device-independent
`txing.board.*` gRPC packages to each other over local sockets, and those
contracts move as a set. A partial upgrade that leaves one binary on an older
release is the worst failure mode this board has: the mismatched pair never
connects, so **video stays down and motion control stops responding with no
local error**. The KVS master retries a bridge that never answers and the
daemon reports the failure to CloudWatch rather than the console, so `rc-status`
shows every service running and the board looks healthy from the console while
being useless. If video or control is missing after an upgrade, confirm all
three `--version` outputs match before investigating anything else.

Because the KVS master is dynamically linked against musl and the installed
Alpine libraries, `apk upgrade` and `mise upgrade` happen together in the
same maintenance window: never upgrade the OS packages without moving to the
release built for them, and never install a release built against a newer
Alpine branch than the device runs. Device apk repositories stay on Alpine
`v3.24` until a coordinated bump. The static daemon and hardware worker
depend only on the kernel and are unaffected by apk upgrades.

```sh
root-rw
apk update
apk upgrade
MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise upgrade txing-<device>-daemon txing-<device>-kvs-master txing-<device>-hardware-worker
/root/.local/share/mise/installs/txing-<device>-daemon/latest/txing-<device>-daemon --version
/root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master --version
/root/.local/share/mise/installs/txing-<device>-hardware-worker/latest/txing-<device>-hardware-worker --version
ldd /root/.local/share/mise/installs/txing-<device>-daemon/latest/txing-<device>-daemon
ldd /root/.local/share/mise/installs/txing-<device>-hardware-worker/latest/txing-<device>-hardware-worker
ldd /root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master | grep -F "libcamera.so.0.7"
ldd /root/.local/share/mise/installs/txing-<device>-kvs-master/latest/txing-<device>-kvs-master | grep -F "libcamera-base.so.0.7"
sync
reboot
```

Do not reboot if any `ldd` output reports `not found` or the expected
libcamera sonames are missing; realign the apk branch and the installed
release first, inside the same window.

Confirm the three binaries speak the current gRPC contracts before rebooting.
Version numbers alone cannot show this: a board can carry matching versions and
still run the superseded per-device packages if it was imaged from an old
release. The package names are embedded in each binary, so `strings` answers it
directly:

```sh
for b in daemon kvs-master hardware-worker; do
  printf '%s: ' "$b"
  strings "/root/.local/share/mise/installs/txing-<device>-$b/latest/txing-<device>-$b" \
    | grep -oE 'txing\.(board|unit|cyberbrick)\.(board_video|hardware)\.v1' \
    | sort -u | tr '\n' ' '
  echo
done
```

Expect `txing.board.board_video.v1` and `txing.board.hardware.v1` from the
daemon, `txing.board.board_video.v1` from the KVS master, and
`txing.board.hardware.v1` from the hardware worker. Any `txing.unit.*` or
`txing.cyberbrick.*` result means that binary predates the unified protocol and
cannot talk to the others; reinstall from a current release before rebooting.

If `apk upgrade` updated the kernel (`linux-rpi`) or the Raspberry Pi boot
firmware, sync the refreshed boot files from the kernel package onto the boot
FAT partition per Alpine's Raspberry Pi sys-install guidance before
rebooting; the Pi firmware only reads the FAT partition.

Bumping the Alpine release (for example a future move off `v3.24`, or a
libcamera soname change inside the branch) is one coordinated change: update
the pinned build image in the board daemon justfile and the release
workflow containers, publish a matching board release built on that
Alpine version, and only then move the device apk repositories and run the
coupled `apk upgrade` + `mise upgrade` window above.

## Local Development

Daemon and native board worker commands:

```sh
just <device>::board::test
just <device>::board::run
just <device>::board::kvs-test-native
just <device>::board::hardware-test-native
just <device>::board::daemon-build-alpine
just <device>::board::kvs-build-alpine
just <device>::board::hardware-build-alpine
just <device>::board::docker-build
just <device>::board::docker-smoke
```

The local daemon uses
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/<device>-daemon}`.
Provision that directory with `just aws::cert <thing-id>` only when AWS
resource changes are intended.

The `*-build-alpine`, `docker-build`, and `docker-smoke` recipes build and
verify inside pinned aarch64 containers and require a native `linux/arm64`
Docker daemon. They assert the linkage contract per binary — static daemon
and hardware worker (no ELF interpreter), musl-dynamic KVS master with the
expected libcamera sonames — and `docker-smoke` executes the static pair on
both `debian:trixie` and pinned Alpine and the KVS master on Alpine, the
same gates the release workflow enforces.
## References

- [Board video bridge contract](../contracts/board-video-bridge.md)
- [Hardware worker contract](../contracts/unit-hardware-worker.md)
- [Unit device contracts](../contracts/unit-device-contracts.md)
- [Board OS: Alpine only, Debian frozen](../constraints/board-os-alpine-only.md)
- [Board (Debian, frozen)](./board-debian-frozen.md)
- [Release artifacts](../artifacts.md)
- [Installation](../installation.md)
- [Development](../development.md)
