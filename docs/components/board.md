# Board

The board is the device-side Raspberry Pi. It is power-switched by the MCU, runs
the root-owned Go daemon plus native workers under OpenRC, and publishes
board-owned runtime state. Unit exposes board MCP for motion control; Cyberbrick
uses the MAVLink contract documented below.

One implementation serves every board device type. Device-specific daemons and
workers are built from `devices/common/board/`; the KVS master is one
device-neutral `txing-board-kvs-master` artifact. Its installed service supplies
the worker identity, capability profile, and bridge sockets at runtime. This
runbook therefore covers every device type.

Every command block in this document is written to be pasted verbatim, with no
placeholders to substitute by hand. The one value that varies is the device
type, carried in `TXING_DEVICE`. Set it once in the shell you are pasting into:

```sh
export TXING_DEVICE=cyberbrick      # or: unit
```

[Confirm OS Baseline](#2-confirm-os-baseline) writes it into the board's
`/root/.profile`, so board shells keep it across the reboots the install
performs. On the operator machine, set it in the shell you work from.
[Generate And Copy Daemon Config](#4-generate-and-copy-daemon-config) adds
`THING_ID` and `BOARD_HOST` for the two commands that need them.

`<device>` still appears in the reference listings above the install steps, where
the blocks describe the *shape* of a path or an artifact name rather than
something to run. Nothing in a `sh` block uses it.

Boards run Alpine Linux with OpenRC. The operating-system baseline below covers
the current and frozen board paths.

## Operating-system baseline

Boards run Alpine Linux with OpenRC. Debian receives no further investment: do
not add Debian or systemd build paths, packages, release artifacts, fixes,
compatibility work, containers, or CI lanes. A board that remains on Debian is
reimaged to Alpine rather than upgraded.

The KVS master is musl-dynamic against stock Alpine libcamera, so camera updates
are Alpine-only. A Debian board stays pinned to its last Debian-built KVS master
and cannot receive a current board release or local gRPC contract update. The
static daemon and hardware worker do not change that rule. Alpine version moves
remain coordinated across the pinned build image, release artifact, and board
apk branch because the KVS master depends on installed Alpine libraries.

The Debian/systemd material in [Board (Debian, frozen)](./board-debian-frozen.md)
is retained solely for existing boards. It is not a supported path for the
current protocol. This decision applies only to the board; the rig and macOS
development paths have independent OS baselines.

## Device Types

Every value that differs between device types is listed here. Nothing else in
this document is device-specific.

| Value | `unit` | `cyberbrick` |
| --- | --- | --- |
| Daemon binary | `txing-unit-daemon` | `txing-cyberbrick-daemon` |
| KVS master binary | `txing-board-kvs-master` | `txing-board-kvs-master` |
| Hardware worker binary | `txing-unit-hardware-worker` | none |
| MAVLink binary | not applicable | `txing-cyberbrick-mavlink` |
| ArduPilot binary/defaults | not applicable | `txing-cyberbrick-ardupilot` and `txing-cyberbrick-ardupilot.defaults.parm` |
| Daemon config directory | `/root/.config/txing/unit-daemon` | `/root/.config/txing/cyberbrick-daemon` |
| Hardware worker socket | `/run/txing-unit-hardware-worker/unit-hardware.sock` | none after MAVLink cutover |
| MCP adapter id | `dev.txing.unit.Daemon` | not applicable |
| MAVLink socket | not applicable | `/run/txing-cyberbrick-mavlink/cyberbrick-mavlink.sock` |
| Device release version file | `release/versions/unit` | `release/versions/cyberbrick` |
| Device release tag prefix | `unit-v` | `cyberbrick-v` |
| Device manifest | `devices/unit/manifest.toml` | `devices/cyberbrick/manifest.toml` |
| Shadow schemas and defaults | `devices/unit/aws/` | `devices/cyberbrick/aws/` |

The daemon derives its values from the device type injected at build time. The
shared KVS master instead reads `TXING_KVS_WORKER_NAME`,
`TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH`, `TXING_MAVLINK_BRIDGE_SOCKET_PATH`, and
the daemon capability profile at service start. Both device types install the
same KVS bytes from `release/versions/kvs-master` / `kvs-master-v*`.

Operator commands are device-owned, matching the MCU commands:

```sh
just ${TXING_DEVICE}::board::nerdctl-build
just ${TXING_DEVICE}::board::nerdctl-smoke
just unit::board::hardware-test-native
just cyberbrick::board::mavlink-build-alpine
```

Board operations that do not depend on the device type stay common-owned, the
same way `just mcu::check` is the shared MCU preflight:

```sh
just common::board::proto-gen           # regenerate the daemon's gRPC bindings
just common::board::kvs-test-native     # test the shared KVS master
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

Neither package carries a device name. They remain the shared Unit board
contracts. Cyberbrick is a device-specific exception: it does not expose Board
MCP and instead has the dedicated local service and daemon bridge in the
[Cyberbrick MAVLink capability contract](../contracts/cyberbrick-mavlink.md).
Unit upgrades its three common binaries as a set. Cyberbrick upgrades daemon,
KVS, MAVLink, and ArduPilot/defaults as a set; see [Maintenance](#maintenance)
for why a partial upgrade is the worst failure this board has.

## Unit Responsibilities

The following hardware/MCP responsibilities are Unit-specific. Cyberbrick
uses the dedicated MAVLink contract linked above.

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
For Unit:

- `REDCON 4`: BLE GATT is confirmed commandable and the device is in the sleep state.
- `REDCON 3`: BLE GATT is confirmed commandable and MCU-controlled wakeup power/D1 is enabled.
- `REDCON 2`: board and MCP are available; video is unavailable or not ready.
- `REDCON 1`: board, MCP, and video are available.

For Cyberbrick, MAVLink replaces MCP. REDCON2 requires board and MAVLink;
REDCON1 additionally requires video and the internal `mavlinkArmed` rule.

The board publishes retained v2 capability state for `board`, the
device-specific control capability, and `video`. `txing-sparkplug-manager`
consumes that retained state directly for REDCON projection. When BLE confirms
REDCON `4` / `power=false`, Sparkplug projection clears board-owned capabilities
and does not reuse stale retained board state on the next wake; fresh board
daemon state must arrive before the device's control capability can become
available again.

## Retained AWS IoT Topics

Board MQTT clients use MQTT 5 for AWS IoT retained service state. Dynamic
freshness signals are retained with a MQTT 5 Message Expiry Interval equal to
`TXING_CAPABILITY_TTL_SECONDS`, which defaults to `150` seconds:

- `txings/<device_id>/capability/v2/state`
- `txings/<device_id>/video/status`

The device-specific control status is retained separately: Unit uses
`txings/<device_id>/mcp/status`; Cyberbrick uses
`txings/<device_id>/mavlink/status`.

The daemon refreshes these dynamic status and capability topics at
`TXING_HEARTBEAT_SECONDS`, which defaults to `60` seconds. Named shadows are
durable read models and are updated only at startup, shutdown, or a semantic
state transition; an unchanged periodic heartbeat does not rewrite them.

Descriptor topics are retained discovery/config records and must not expire:

- `txings/<device_id>/video/descriptor`

The corresponding Unit MCP and Cyberbrick MAVLink descriptor topics use the
same retention rule.

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
- worker binary: `txing-board-kvs-master`

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
worker is ready enough for the daemon to advertise video availability; it is
not a media-quality guarantee or a control-transport readiness signal.

The shared board video contract is documented in
[Board video](./board-video.md).

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
/root/.config/txing/<device>-daemon/SFSRootCAG2.pem
/root/.config/txing/<device>-daemon/certificate.arn
/root/.config/txing/<device>-daemon/certificate.pem.crt
/root/.config/txing/<device>-daemon/private.pem.key
/root/.config/txing/<device>-daemon/public.pem.key
/root/.config/txing/<device>-daemon/services/txing-*
```

`daemon.env` is an environment file rendered from
`devices/common/daemon.env.template`. It uses plain `KEY=value` lines so
both the OpenRC hardware-worker script and the daemon can consume the same
root-owned file. The `services/` directory contains the complete board OpenRC
catalog; installation copies only the services for the selected device type.
Certificate paths are omitted by default; the daemon derives colocated paths
from the loaded `daemon.env` directory. For manual shell export, use
`set -a; . /root/.config/txing/<device>-daemon/daemon.env; set +a`.

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

- Alpine Linux aarch64 on a supported Raspberry Pi board, **sys install**
  (`setup-disk -m sys`), device apk repositories on the Alpine `v3.24` branch.
- Default Alpine stack: apk, ifupdown-ng + wpa_supplicant + udhcpc
  networking, busybox ntpd time sync, OpenRC init. No systemd and no
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
- A supported video board exposes the Raspberry Pi `rpi/vc4` libcamera
  pipeline for an attached supported CSI camera and the BCM2835 H.264 encoder
  at `/dev/video11`. Alpine aarch64 alone does not imply those capabilities.
  Linking the KVS master against libcamera is therefore necessary but not
  sufficient for video. Camera capture additionally requires the Raspberry Pi
  pipeline handler, IPA module, and sensor tuning files
  (`libcamera-raspberrypi`), a running udev daemon for libcamera's enumerator
  (`eudev`), camera configuration in `/boot/usercfg.txt`, and the
  `bcm2835-codec` and `bcm2835-isp` kernel modules. None of these are implied
  by the build container's package set or by `ldd` linkage checks, and every
  one of them fails as the same KVS master error,
  `configured camera index is not available`. See
  [Confirm OS Baseline](#2-confirm-os-baseline),
  [Enable Udev](#2a-enable-udev), and
  [Enable PWM Overlay And Camera](#5-enable-pwm-overlay-and-camera).
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
  across all three plus a new shared KVS release; see
  [Maintenance](#maintenance).

## Release Artifacts

Unit installs its daemon and hardware worker from `unit-v*`. Cyberbrick installs
its daemon, MAVLink, and ArduPilot from `cyberbrick-v*`. Both install the exact
same KVS master from the independent `kvs-master-v*` stream.

```text
# Unit
txing-unit-daemon-linux-aarch64.tar.gz
txing-unit-hardware-worker-linux-aarch64.tar.gz

# Cyberbrick
txing-cyberbrick-daemon-linux-aarch64.tar.gz
txing-cyberbrick-mavlink-linux-aarch64.tar.gz
txing-cyberbrick-ardupilot-linux-aarch64.tar.gz

# Shared board KVS master
txing-board-kvs-master-linux-aarch64.tar.gz
```

Every daemon, KVS, MAVLink, and hardware-worker archive contains its one
root-level executable. The Cyberbrick ArduPilot archive contains both
`txing-cyberbrick-ardupilot` and
`txing-cyberbrick-ardupilot.defaults.parm`; OpenRC loads the defaults on every
tmpfs-backed boot. Boards use root's persistent mise config and install tree:

```text
/root/.config/mise/conf.d/txing-<device>-daemon.toml
/root/.local/share/mise/installs/txing-<device>-daemon/latest/txing-<device>-daemon
/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker
/root/.local/share/mise/installs/txing-cyberbrick-mavlink/latest/txing-cyberbrick-mavlink
/root/.local/share/mise/installs/txing-cyberbrick-ardupilot/latest/txing-cyberbrick-ardupilot
```

Root-owned `mise` configs use `version_prefix = "<device>-v"` for device
artifacts and `version_prefix = "kvs-master-v"` for the shared KVS artifact, so
each `latest` resolves within its owning release stream. This release model is forward-only;
replace old board configs manually if they do not include the component prefix. Service starts are offline by design:
restarting an OpenRC service does not install or upgrade tools, invoke mise,
or call GitHub. If a board needs new binaries, follow
[Maintenance](#maintenance).

Cyberbrick's corresponding patched ArduPilot source archive is published for
provenance but is not installed on the board. Its current runtime installation
and operational steps are in [Cyberbrick runtime](#cyberbrick-runtime).

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

- A supported Raspberry Pi board (for example a Pi Zero 2 W or Pi 3) with an
  attached supported CSI camera when KVS video is required
- Alpine Linux aarch64 Raspberry Pi image from the `v3.24` branch
- AWS resources and the target thing already exist
  (`just aws::deploy` once per stack, then
  `just aws::deploy-device <raspi-rig-id> <device> <name>`)
- daemon environment/certificate archive has been generated on the operator
  machine

### 1. Create The Card And Sys Install

Prepare the card so the board comes up on Wi-Fi with ssh reachable, and drive
the rest of the install remotely. Nothing here is generated: the files in
`devices/common/board/card/` are the files as they land on the card.

Write the card with Raspberry Pi Imager. Choose the Alpine `v3.24` Raspberry Pi
**aarch64** image; if it is not in the OS list, download it from
[alpinelinux.org/downloads](https://alpinelinux.org/downloads/) and use *Use
custom*. Alpine has supported image files with resizable partitions since 3.23,
so the pinned `v3.24` works with Imager directly.

Two things to get right in Imager:

- **Skip the OS customisation prompt.** Its hostname, Wi-Fi, and ssh settings are
  written in a Raspberry Pi OS format that Alpine ignores. Answer no; the files
  below do that job.
- **Use a card larger than the image.** `unattended.sh` creates the root
  partition in the free space that is left, so a card with nothing spare cannot
  convert to a sys install.

Re-insert the card. The FAT boot partition mounts on its own; everything below
goes in its root.

Then copy these onto the root of the FAT boot partition:

| File | Where from | Edit |
| --- | --- | --- |
| `headless.apkovl.tar.gz` | [macmpi/alpine-linux-headless-bootstrap](https://github.com/macmpi/alpine-linux-headless-bootstrap) | no, used unmodified |
| `wpa_supplicant.conf` | `devices/common/board/card/` | SSID, passphrase, `country=` |
| `authorized_keys` | `devices/common/board/card/` | your operator public key |
| `interfaces` | `devices/common/board/card/` | no, pins the board to `wlan0` |
| `unattended.sh` | `devices/common/board/card/` | `HOSTNAME`; `TIMEZONE` defaults to `Europe/Berlin` |
| `opt-out` | `devices/common/board/card/` | no, empty by design |

The apkovl is a standard Alpine overlay tarball and there is nothing to change
inside it. The rest of the configuration is supplied by the plain files beside
it, which it reads off the boot partition on first boot: it brings up
networking, starts sshd, and installs the operator key.

Three things that bite, all of which produce a board that looks dead in the same
way:

- `wpa_supplicant.conf` must have **LF line endings**. Saved with CRLF it is
  silently ignored and the board comes up with no Wi-Fi, which is
  indistinguishable from a wrong passphrase.
- Supply `authorized_keys`. Without it the bootstrap leaves root reachable over
  ssh with **no password**, which is not acceptable on a deployment network.
- `country=` must match where the board runs, or the regulatory domain can
  disable the channel the access point is on.

Keep your edited copies outside the repository: they carry the Wi-Fi passphrase.
They carry base OS setup only, so a lost card carries no device identity and no
cloud access; AWS credentials, daemon config, and release material stay in the
manual steps below.

Boot the board. `unattended.sh` runs as root once networking is up and takes the
board the rest of the way on its own: it enables the community repository,
upgrades packages, installs the fixed runtime package baseline, creates the
root partition in the free space after the boot FAT, runs `setup-alpine` for
the sys install, and reboots into it. No console login and no interactive
setup.

It stops after the OS baseline. Release binaries, udev runlevel setup, camera
configuration, device configuration, and services remain manual steps below,
performed over ssh.

Two properties worth knowing, because they decide whether a bad run is
recoverable:

- **The Wi-Fi configuration and operator key are written onto the new root
  explicitly**, and the script refuses to reboot unless they are present along
  with the `networking`, `wpa_supplicant`, and `sshd` runlevel links. The overlay
  is applied to the tmpfs root of the diskless boot and is *not* applied again
  once the board boots from `mmcblk0p2`, so anything that existed only because
  the overlay was unpacked would otherwise be gone. A board that fails this check
  stays up on the diskless boot, which is reachable; one that rebooted without it
  would need physical recovery.
- **The root filesystem is left writable.** A board that provisioned incorrectly
  has to be fixable over ssh. Sealing it read-only is a later, deliberate step.

Re-running is safe: if `/dev/mmcblk0p2` already holds a filesystem the script
refuses to repartition and exits, so an interrupted attempt cannot destroy a
board that already converted.

Once the board comes back on the network, confirm it landed where it should
before continuing:

```sh
mount | grep ' / '        # /dev/mmcblk0p2 ... rw   (sys install, writable)
rc-status default | grep -E 'networking|wpa_supplicant|sshd'
sshd -T | grep -iE 'passwordauth|permitrootlogin'
mise --version             # installed by the card, on root's PATH
```

`sshd -T` prints the *effective* configuration. It must show
`permitrootlogin prohibit-password` and `passwordauthentication no`: the image
ships with an empty root password, so a board that accepts password logins over
Wi-Fi is open.

`mise` and the fixed Alpine runtime package baseline are installed by the card
before its first reboot. Everything past that baseline -- udev runlevel setup,
camera configuration, release binaries, daemon config, and services -- is still
a manual step below.

The board boots **read-only**, with `/tmp`, `/var/tmp`, `/var/log`, and
on tmpfs, `/etc/resolv.conf` pointed at udhcpc's runtime
output, and the `root-rw` / `root-ro` aliases installed for `root`. Run
`root-rw` before the steps below: apk installs, mise installs, daemon config,
and OpenRC changes all need a writable root. `root-ro` puts it back, and
[Final Reboot Check](#8-final-reboot-check) is the last step.

`/root/txing-unattended.log` on the board records how it was provisioned. It is
in `/root` rather than `/var/log` because the tmpfs mount would shadow it.

Continue over ssh from [Confirm OS Baseline](#2-confirm-os-baseline).

If you would rather drive base setup by hand instead, the same answers are:

```sh
setup-alpine
```

Answers that matter for a board:

- hostname: any stable name; board identity is the thing id carried in the
  daemon config, the hostname is cosmetic
- interface: `wlan0` with the deployment Wi-Fi SSID and passphrase
  (setup-alpine configures ifupdown-ng + wpa_supplicant + udhcpc), or `eth0`
  with a wired adapter
- NTP client: `busybox` ntpd
- timezone: `Europe/Berlin`
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
`setup-disk` did not already do it:

```sh
mount -o remount,rw /media/mmcblk0p1
grep -q 'root=/dev/mmcblk0p2' /media/mmcblk0p1/cmdline.txt \
  || sed -i 's|$| root=/dev/mmcblk0p2|' /media/mmcblk0p1/cmdline.txt
```

After reviewing the successful result, reboot manually into the sys install.

All remaining steps run as `root` on the sys install while the root
filesystem is still writable. `setup-disk -m sys` writes a UUID-based
`/etc/fstab` and mounts the boot FAT at `/boot` (not `/media/mmcblk0p1`, which
only existed during the diskless boot above); steps 5 and 7 use `/boot` and
those UUIDs.

### 2. Confirm OS Baseline

This is the first step over ssh. Make the root writable and record the device
type, so every later block on this board pastes as written — including after the
reboots below, because `/root/.profile` survives them:

```sh
root-rw
export TXING_DEVICE=cyberbrick      # or: unit
grep -qxF "export TXING_DEVICE=$TXING_DEVICE" /root/.profile \
  || echo "export TXING_DEVICE=$TXING_DEVICE" >> /root/.profile
echo "device type: $TXING_DEVICE"
```

This is the only value you edit by hand on the board; every block below reads it,
so a typo surfaces immediately as a wrong binary name rather than quietly later.
[Generate And Copy Daemon Config](#4-generate-and-copy-daemon-config) sets two
more on the *operator* machine.

`root-rw` is an alias the card installed in `/root/.profile`. On a board built by
hand the root is not read-only yet, so it reports `not found` and the rest of the
block runs unaffected.

First, the `community` repository. This one line is needed only on a board
brought up by hand, where `setup-alpine` enables `main` alone while libcamera,
grpc, and re2 ship in `community`. On a card-provisioned board `unattended.sh`
already wrote both over https, so it changes nothing — run it anyway, it is
harmless either way:

```sh
sed -i 's|^#\(http.*/community\)$|\1|' /etc/apk/repositories
```

The card installs the fixed runtime package baseline into the persistent root
before its first reboot. Confirm it before moving on, because everything
downstream assumes it:

```sh
apk info -e libstdc++ libcamera libcamera-raspberrypi eudev grpc protobuf iproute2 \
  | sort | tr '\n' ' '; echo
```

All seven named packages must be listed.

`iproute2` supplies `ss`, used below to confirm that ArduPilot's MAVLink
endpoint is restricted to `127.0.0.1:14550` both before and after the local
MAVLink service connects.

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
udev database, so switch device management to udev before starting the device
runtime. `setup-udev` from `alpine-conf` is not present on all Alpine images;
wire the services directly, which is equivalent and image-independent:

```sh
for s in udev udev-trigger udev-settle; do rc-update add $s sysinit; done
rc-service udev start
rc-service udev-trigger start
```

Verify:

```sh
rc-status sysinit | grep -i udev
udevadm info --export-db | grep -c '^P:'
```

All three services must show `started`, and the device count must be in the
hundreds. `udev-trigger` is the one that matters and the one easiest to skip:
`udevd` alone starts happily with an **empty database**, and libcamera reads the
database rather than the devices, so it enumerates zero cameras while
`/run/udev` exists, `rc-service udev status` says `started`, and `/dev/media0`
behaves perfectly. Do not use `ls -d /run/udev` as the check — see
[Camera Does Not Enumerate](#camera-does-not-enumerate).

The three services must land in **`sysinit`**, not `default`: device
enumeration has to complete before the txing services start, and `sysinit`
placement is also what makes this survive the read-only-root reboot in
[Configure Read-Only Root](#7-configure-read-only-root). A board where video
works before a reboot and fails after it is almost always udev left in the
wrong runlevel.

### 3. Install Mise

The card's `unattended.sh` already installed `mise` into `/root/.local/bin` and
added it to `/root/.profile`, so `mise --version` works on a freshly provisioned
board. This section is the reference for what it did, and for boards being
brought up by hand.

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

On the operator machine, set the thing id and the board's ssh host once, then
paste:

```sh
export TXING_DEVICE=cyberbrick      # or: unit
export THING_ID=...                 # the AWS IoT thing id for this board
export BOARD_HOST=...               # hostname or address you ssh to

just aws::cert "$THING_ID"
scp "certs/${THING_ID}/${THING_ID}-daemon-config.tgz" \
  "root@${BOARD_HOST}:/tmp/${THING_ID}-daemon-config.tgz"
```

On the board, `TXING_DEVICE` is already set from step 2. `THING_ID` is not — it
is needed only to name the archive that was just copied in, so read it off the
file rather than typing it a second time into a second shell:

```sh
CONFIG_DIR="$HOME/.config/txing/${TXING_DEVICE}-daemon"
CONFIG_TGZ="$(ls -1t /tmp/*-daemon-config.tgz | head -1)"
echo "installing $CONFIG_TGZ into $CONFIG_DIR"

install -d -m 700 "$CONFIG_DIR"
tar --no-same-owner -xzf "$CONFIG_TGZ" -C "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
chmod 600 "$CONFIG_DIR/daemon.env"
chmod 600 "$CONFIG_DIR/certificate.arn"
chmod 600 "$CONFIG_DIR/certificate.pem.crt"
chmod 600 "$CONFIG_DIR/private.pem.key"
chmod 600 "$CONFIG_DIR/public.pem.key"
chmod 644 "$CONFIG_DIR/AmazonRootCA1.pem"
chmod 644 "$CONFIG_DIR/SFSRootCAG2.pem"
for service in \
  txing-unit-hardware-worker \
  txing-unit-daemon \
  txing-kvs-master \
  txing-cyberbrick-ardupilot \
  txing-cyberbrick-mavlink \
  txing-cyberbrick-daemon; do
  test -x "$CONFIG_DIR/services/$service"
done
rm -f "$CONFIG_TGZ"
```

The `echo` before the install is deliberate: `ls -1t` picks the newest matching
archive, so on a board that has been reprovisioned it is worth seeing which one
was chosen before it is unpacked over the live config.

`AmazonRootCA1.pem` is the daemon's MQTT trust root; `SFSRootCAG2.pem` is the
Starfield Services Root CA G2 that the KVS master's signaling TLS verifies
against (see [OS And ABI Contract](#os-and-abi-contract)). Both are fetched
from AWS's public repository by `just aws::cert` and shipped in the bundle.
Every board bundle also contains the complete OpenRC service catalog under
`services/`. KVS has one common service-owned script. The runtime section
installs it under the selected device type's OpenRC name and copies only the
other relevant scripts into `/etc/init.d`.

`daemon.env` is rendered from
`devices/common/daemon.env.template` and uses plain `KEY=value`
lines so both the daemon and the hardware worker init script can consume the
same root-owned file. Certificate paths are omitted by default; the daemon
derives colocated paths from the loaded `daemon.env` directory. For manual
shell export, use
`set -a; . /root/.config/txing/${TXING_DEVICE}-daemon/daemon.env; set +a`.
Motor calibration, including
`TXING_MOTOR_LEFT_TRACK_POWER_PERCENT`/`TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT`
track trim, follows the board contract above.

If the device daemon role policy needs to be refreshed later (for example
after policy changes on the operator side), run this on the operator machine:

```sh
just ${TXING_DEVICE}::board::role-policy "$THING_ID"
```

### 5. Enable PWM Overlay And Camera

Both of these need a reboot to take effect, so they come before the services
rather than after. The hardware worker looks for `/sys/class/pwm/pwmchip0` at
every start and the KVS master enumerates cameras at every start; if the
services come up first, both fail on hardware that is merely not configured yet,
and the logs from that first start have to be read past rather than trusted.
With this step done first, [Install Runtime And OpenRC
Services](#6-install-runtime-and-openrc-services) is verified against the
hardware the board will actually run.

After `setup-disk -m sys`, the boot FAT partition is mounted at `/boot` (the
`/media/mmcblk0p1` mount only exists during the diskless boot in step 1).
Alpine's managed `/boot/config.txt` explicitly says not to modify it because a
bootloader upgrade replaces it. Its `include usercfg.txt` line makes
`/boot/usercfg.txt` the persistent operator configuration file. Refuse to
continue if that include is absent rather than writing to managed `config.txt`:

```sh
grep -qxF 'include usercfg.txt' /boot/config.txt || {
  echo '/boot/config.txt must include usercfg.txt; do not modify config.txt' >&2
  exit 1
}

grep -qxF 'dtoverlay=pwm-2chan' /boot/usercfg.txt ||
  echo 'dtoverlay=pwm-2chan' >> /boot/usercfg.txt
```

The `pwm-2chan.dtbo` overlay ships in Alpine's `raspberrypi-bootloader`
content already present on the boot FAT partition. Its standard two-channel
mapping is GPIO 18 for PWM0 and GPIO 19 for PWM1; the patched ArduPilot target
uses the corresponding `pwmchip0` channels 0 and 1, so it needs no extra
`usercfg.txt` parameters. `/sys/class/pwm/pwmchip0` appears only after a reboot;
until then the hardware worker logs `PWM chip path does not exist` on every
start. The camera changes below need a reboot too, so the single one at the end
of this step covers both.

Enable firmware autodetection for the connected supported CSI camera and the
two kernel modules needed by the current KVS video path. These settings belong
in `usercfg.txt`; nothing in the base Alpine image enables them:

```sh
grep -qxF 'camera_auto_detect=1' /boot/usercfg.txt ||
  echo 'camera_auto_detect=1' >> /boot/usercfg.txt

for m in bcm2835-codec bcm2835-isp; do
  grep -qx "$m" /etc/modules || echo "$m" >> /etc/modules
done
```

`camera_auto_detect=1` makes the firmware probe the CSI sensor over I²C and
load the matching overlay. A successful boot exposes the sensor and a
`unicam-image` node; its `/dev/videoN` number is not a contract. If the known
supported camera is not detected after this reboot, add that camera's explicit
`dtoverlay=` line to `usercfg.txt` and reboot again. For example, the Raspberry
Pi Camera Module v2.1 uses `dtoverlay=imx219`. Do not add an overlay for an
unknown sensor: reseat the CSI cable and identify the camera first.

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
`imx219` or `ov5647`), one `unicam-image` node at any `/dev/videoN`, and the
BCM2835 H.264 encoder at `/dev/video11`. Expect a `unicam` media controller
plus codec and ISP media controllers; their count and numbering vary by
Raspberry Pi model and kernel probe order.

Confirm the PWM chip appeared as well, since the services in the next step
depend on it:

```sh
ls -d /sys/class/pwm/pwmchip0
```

Resolve anything missing here before continuing.
[Camera Does Not Enumerate](#camera-does-not-enumerate) works down the video
pipeline in order; a missing `pwmchip0` means the overlay line did not land in
the firmware-read `usercfg.txt`.

The reboot also reseals the root filesystem read-only on a card-provisioned
board, so the next step starts by making it writable again.

### 6. Install Device Runtime And OpenRC Services

Everything above this point is a prerequisite of what follows, and each one fails
later and confusingly if skipped: missing apk packages surface as a wall of
`Error loading shared library` from a binary that is actually correct, and an
untriggered udev surfaces as `configured camera index is not available` from a
camera that is actually working. Confirm all of it in one paste first:

```sh
printf 'step 2  packages: '
apk info -e libstdc++ libcamera libcamera-raspberrypi eudev grpc protobuf iproute2 \
  | sort | tr '\n' ' '; echo

printf 'step 2a runlevel: '
rc-status sysinit | grep -c -E 'udev|udev-trigger|udev-settle'

printf 'step 2a database: '
command -v udevadm >/dev/null \
  && udevadm info --export-db | grep -c '^P:' \
  || echo 'udevadm absent - eudev not installed, do step 2 first'

printf 'step 5  hardware: '
ls -d /sys/class/pwm/pwmchip0 /dev/video11 2>&1 | tr '\n' ' '; echo
for d in /sys/class/video4linux/video*; do
  [ "$(cat "$d/name")" = unicam-image ] && echo "camera: /dev/$(basename "$d")"
done

printf 'step 2  device:   %s\n' "${TXING_DEVICE:?run step 2 first}"
```

Each line names the step that fixes it:

| Line | Expected |
| --- | --- |
| `step 2 packages` | all seven named |
| `step 2a runlevel` | `3` |
| `step 2a database` | hundreds, not `0` |
| `step 5 hardware` | `pwmchip0`, the H.264 encoder at `video11`, and one `camera:` line |
| `step 2 device` | `unit` or `cyberbrick` |

These fail in a chain, so fix them in step order: without step 2's package
baseline there is no `eudev`, so step 2a's `rc-update add udev sysinit` fails
too and one missing package shows up as three broken lines. Fixing it here costs
minutes; found later it is a wall of `Error loading shared library` from a
correct binary, or `configured camera index is not available` from a working
camera.

#### Unit runtime

The following runtime install is for **Unit only**. It installs the Unit daemon,
KVS master, and hardware worker. Cyberbrick uses [Cyberbrick
runtime](#cyberbrick-runtime) below. Both `"0s"` settings exist
because a board installs first-party releases minutes after they are published,
which is exactly the case each default is tuned against:

- `minimum_release_age` opts out of mise's 24-hour supply-chain filter. Left at
  the default, `latest` resolves to nothing and mise warns about a date filter.
- `fetch_remote_versions_cache` opts out of caching the remote version list. Left
  at a non-zero window, a release published inside that window is invisible:
  `mise upgrade` reports *All tools are up to date* and stays on the old
  version, with no warning and nothing in `mise ls-remote` to suggest a newer
  release exists. This matches `rig/install-mise-tools.sh`. On a board still
  carrying a cached window, `mise cache clear` forces the re-read.

The reboot at the end of the previous step brought the root back up **read-only**
on a card-provisioned board, so make it writable again before anything here
writes a file. `root-rw` covers the rest of this step and step 7; it is
idempotent, so running it on an already-writable root is harmless.

```sh
: "${TXING_DEVICE:?run step 2 first, or export TXING_DEVICE}"
test "$TXING_DEVICE" = unit || {
  echo 'This Unit runtime block does not apply to Cyberbrick; use Cyberbrick runtime.' >&2
  exit 1
}
root-rw

install -d -m 700 /root/.config/mise/conf.d /root/.local/share/mise
cat >/root/.config/mise/conf.d/txing-${TXING_DEVICE}-daemon.toml <<EOF
[settings]
fetch_remote_versions_cache = "0s"
minimum_release_age = "0s"

[tool_alias]
txing-${TXING_DEVICE}-daemon = "github:mparkachov/txing"
txing-board-kvs-master = "github:mparkachov/txing"
txing-${TXING_DEVICE}-hardware-worker = "github:mparkachov/txing"

[tools.txing-${TXING_DEVICE}-daemon]
version = "latest"
version_prefix = "${TXING_DEVICE}-v"
asset_pattern = "txing-${TXING_DEVICE}-daemon-linux-aarch64.tar.gz"

[tools.txing-board-kvs-master]
version = "latest"
version_prefix = "kvs-master-v"
asset_pattern = "txing-board-kvs-master-linux-aarch64.tar.gz"

[tools.txing-${TXING_DEVICE}-hardware-worker]
version = "latest"
version_prefix = "${TXING_DEVICE}-v"
asset_pattern = "txing-${TXING_DEVICE}-hardware-worker-linux-aarch64.tar.gz"
EOF

MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise install \
    txing-${TXING_DEVICE}-daemon@latest \
    txing-board-kvs-master@latest \
    txing-${TXING_DEVICE}-hardware-worker@latest
```

The `: "${TXING_DEVICE:?...}"` guard is the first line of every block from here
on that writes files. With `TXING_DEVICE` unset these heredocs would otherwise
expand to paths like `txing--daemon` and write plausible-looking rubbish, so the
blocks refuse to start instead.

Check the resolved binaries before writing the services. Every binary must
report the release version; the static daemon and hardware worker must show
no shared-library dependencies (musl `ldd` refuses them or lists only the
loader), and the musl-dynamic KVS master must use the musl interpreter and
resolve all shared libraries:

```sh
test "${TXING_DEVICE:?export the board device type}" = unit || {
  echo 'Use the Cyberbrick runtime instructions below.' >&2
  exit 1
}
INSTALLS=/root/.local/share/mise/installs
DAEMON="$INSTALLS/txing-${TXING_DEVICE}-daemon/latest/txing-${TXING_DEVICE}-daemon"
KVS="$INSTALLS/txing-board-kvs-master/latest/txing-board-kvs-master"
WORKER="$INSTALLS/txing-${TXING_DEVICE}-hardware-worker/latest/txing-${TXING_DEVICE}-hardware-worker"

/root/.local/bin/mise list
"$DAEMON" --version
"$KVS" --version
"$WORKER" --version
ldd "$DAEMON" || true
ldd "$WORKER" || true
ldd "$KVS"
ldd "$KVS" | grep -F "libcamera.so.0.7"
ldd "$KVS" | grep -F "libcamera-base.so.0.7"
```

`INSTALLS`, `DAEMON`, `KVS`, and `WORKER` are plain shell variables, not
exported: nothing the daemon reads may leak in from an operator shell, for the
reason given in [Video Never Reaches READY](#video-never-reaches-ready). Every
later block that needs them redeclares them, so each stays self-contained after
a reconnect.

Confirm the KVS signaling anchor provisioned with the daemon config is
present and names the expected root:

```sh
openssl x509 -in "/root/.config/txing/${TXING_DEVICE}-daemon/SFSRootCAG2.pem" \
  -noout -subject
```

The subject must name `Starfield Services Root Certificate Authority - G2`.
The KVS service points its TLS at this file through
`TXING_KVS_SYSTEM_CA_CERT_PATH` (set in the init script below), because the
SDK cannot verify the signaling chain against the full OS bundle. This anchor
is stable (valid to 2037).

Install the Unit-owned OpenRC init scripts from the daemon config bundle.
There is no OpenRC equivalent of
unit's `txing-unit.target`; each service is enabled individually and OpenRC
dependencies order them hardware worker, then daemon, then KVS master. The
daemon owns the board-video bridge socket; the KVS master connects to it as a
separate service. The hardware worker owns the BoardHardware socket; the
daemon connects to it as a client and degrades if it is unavailable. All
three services run under `supervise-daemon`, which restarts them on failure
with bounded respawn limits. The daemons exit cleanly on the default
supervise-daemon stop signal.

```sh
: "${TXING_DEVICE:?run step 2 first, or export TXING_DEVICE}"
SERVICE_DIR=/root/.config/txing/${TXING_DEVICE}-daemon/services
install -m 755 \
  "$SERVICE_DIR/txing-unit-hardware-worker" \
  /etc/init.d/txing-unit-hardware-worker
install -m 755 "$SERVICE_DIR/txing-unit-daemon" /etc/init.d/txing-unit-daemon
install -m 755 "$SERVICE_DIR/txing-kvs-master" /etc/init.d/txing-unit-kvs-master
for s in hardware-worker daemon kvs-master; do
  service=txing-${TXING_DEVICE}-$s
  sh -n "/etc/init.d/$service"
done
```

Silence means the three installed scripts are syntactically valid. The binary
checks immediately above already confirmed their commands exist. Then enable
and start them, dependencies first:

```sh
rc-update add txing-${TXING_DEVICE}-hardware-worker default
rc-update add txing-${TXING_DEVICE}-daemon default
rc-update add txing-${TXING_DEVICE}-kvs-master default
rc-service txing-${TXING_DEVICE}-hardware-worker restart
rc-service txing-${TXING_DEVICE}-daemon restart
rc-service txing-${TXING_DEVICE}-kvs-master restart
```

Verify:

```sh
rc-status default
for s in hardware-worker daemon kvs-master; do
  rc-service txing-${TXING_DEVICE}-$s status
done
for s in hardware-worker daemon kvs-master; do
  echo "== $s"
  tail -n 160 /var/log/txing-${TXING_DEVICE}-$s.log
done
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
- the worker logs version and local actuator readiness. `PWM chip path does not
  exist` is a **failure** here, not a pending step: the overlay went in at
  [Enable PWM Overlay And Camera](#5-enable-pwm-overlay-and-camera) and the
  board has rebooted since
- MQTT connects and retained `board`, dynamic `mcp`, and `video` state is
  published (visible in CloudWatch)
- the KVS master reaches READY over the bridge, because the camera was enabled
  in the previous step. `configured camera index is not available` followed by
  supervise-daemon retiring it to `failed` is expected only when no camera is
  physically attached; with one attached it is a fault, and
  [Camera Does Not Enumerate](#camera-does-not-enumerate) works down the
  pipeline
- REDCON can reach `1` after Sparkplug projection sees fresh `board`, `mcp`,
  and `video` capability state

#### Cyberbrick runtime

Cyberbrick starts ArduPilot, MAVLink, the daemon, and KVS master in that order.
ArduPilot is the only PWM owner. There is no
direction GPIO, 20 kHz H-bridge mode, MCP compatibility shim, or
hardware worker. Keep the rover lifted and motor power isolated until the
separate physical-acceptance work is approved.

Provision the MAVLink KVS resource and IAM policy from the operator
workstation before touching the board. The current base stack must deploy
successfully first, then generate a fresh Cyberbrick bundle:

```sh
: "${TXING_AWS_STACK:?export the selected stack prefix}"
: "${THING_ID:?export the Cyberbrick Thing id}"
just aws::deploy
just aws::cert "$THING_ID"
```

Copy and unpack `<thing-id>-daemon-config.tgz` to
`/root/.config/txing/cyberbrick-daemon/`. Its `mavlink` capability and role
authorize both `<thing-id>-board-video` and `<thing-id>-mavlink`.

In one writable-root window, install the three `cyberbrick-v*` artifacts and
the shared `kvs-master-v*` artifact together:

```sh
export TXING_DEVICE=cyberbrick
root-rw
install -d -m 700 /root/.config/mise/conf.d /root/.local/share/mise
cat >/root/.config/mise/conf.d/txing-cyberbrick-runtime.toml <<'EOF'
[settings]
fetch_remote_versions_cache = "0s"
minimum_release_age = "0s"

[tool_alias]
txing-cyberbrick-daemon = "github:mparkachov/txing"
txing-board-kvs-master = "github:mparkachov/txing"
txing-cyberbrick-mavlink = "github:mparkachov/txing"
txing-cyberbrick-ardupilot = "github:mparkachov/txing"

[tools.txing-cyberbrick-daemon]
version = "latest"
version_prefix = "cyberbrick-v"
asset_pattern = "txing-cyberbrick-daemon-linux-aarch64.tar.gz"
[tools.txing-board-kvs-master]
version = "latest"
version_prefix = "kvs-master-v"
asset_pattern = "txing-board-kvs-master-linux-aarch64.tar.gz"
[tools.txing-cyberbrick-mavlink]
version = "latest"
version_prefix = "cyberbrick-v"
asset_pattern = "txing-cyberbrick-mavlink-linux-aarch64.tar.gz"
[tools.txing-cyberbrick-ardupilot]
version = "latest"
version_prefix = "cyberbrick-v"
asset_pattern = "txing-cyberbrick-ardupilot-linux-aarch64.tar.gz"
EOF

MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise install \
    txing-cyberbrick-daemon@latest \
    txing-board-kvs-master@latest \
    txing-cyberbrick-mavlink@latest \
    txing-cyberbrick-ardupilot@latest
```

The ArduPilot archive supplies both the executable and its defaults file;
no source checkout is installed on the board.

Install the Cyberbrick OpenRC services from the daemon config bundle. They
order ArduPilot, MAVLink,
daemon, then KVS master. KVS depends on the daemon, not MAVLink directly,
so video/camera faults cannot stop the control transport.

```sh
SERVICE_DIR=/root/.config/txing/cyberbrick-daemon/services
install -m 755 \
  "$SERVICE_DIR/txing-cyberbrick-ardupilot" \
  /etc/init.d/txing-cyberbrick-ardupilot
install -m 755 \
  "$SERVICE_DIR/txing-cyberbrick-mavlink" \
  /etc/init.d/txing-cyberbrick-mavlink
install -m 755 \
  "$SERVICE_DIR/txing-cyberbrick-daemon" \
  /etc/init.d/txing-cyberbrick-daemon
install -m 755 "$SERVICE_DIR/txing-kvs-master" /etc/init.d/txing-cyberbrick-kvs-master
for s in ardupilot mavlink daemon kvs-master; do
  service=txing-cyberbrick-$s
  sh -n "/etc/init.d/$service"
done
```

Enable the complete service set, verify it, then return the root to
read-only:

```sh
for s in ardupilot mavlink daemon kvs-master; do
  rc-update add "txing-cyberbrick-$s" default
  rc-service "txing-cyberbrick-$s" restart
done
rc-status default
for s in ardupilot mavlink daemon kvs-master; do
  rc-service "txing-cyberbrick-$s" status
done
test ! -e /etc/init.d/txing-cyberbrick-hardware-worker
test ! -e /root/.local/share/mise/installs/txing-cyberbrick-hardware-worker
! rc-status default | grep -F txing-cyberbrick-hardware-worker
ss -uanp | grep -F '127.0.0.1:14550'
! ss -uanp | grep -F '0.0.0.0:14550'
grep -F -- '--defaults' /etc/init.d/txing-cyberbrick-ardupilot
grep -Fx 'FS_GCS_TIMEOUT 1' /root/.local/share/mise/installs/txing-cyberbrick-ardupilot/latest/txing-cyberbrick-ardupilot.defaults.parm
grep -Fx 'SERVO1_FUNCTION 73' /root/.local/share/mise/installs/txing-cyberbrick-ardupilot/latest/txing-cyberbrick-ardupilot.defaults.parm
grep -Fx 'SERVO2_FUNCTION 74' /root/.local/share/mise/installs/txing-cyberbrick-ardupilot/latest/txing-cyberbrick-ardupilot.defaults.parm
root-ro
sync
```

Use `ss -a`, not `ss -l`, for this check. ArduPilot initially binds the
`udpin:` endpoint, then connects that UDP socket to the first sender after the
MAVLink service transmits. At that point `ss -lunp` hides the healthy connected
socket. The expected steady state is two loopback `ESTAB` rows: ArduPilot at
`127.0.0.1:14550` and the MAVLink service at an ephemeral local port, each
pointing at the other. Empty ArduPilot and MAVLink stdout logs are normal when
neither process has an error to report.

After reviewing the successful checks, reboot manually. It is deliberately
separate from the copy-paste block.

After reconnecting, repeat the service, local-UDP, defaults, and no-worker
checks. Deploy Office through its normal Cloudflare Pages Git deployment
only after that reboot. Finally, use the AWS IoT console to manually delete
the obsolete `<thing-id>` named `mcp` shadow and clear retained
`txings/<thing-id>/mcp/descriptor` and `txings/<thing-id>/mcp/status`
messages with zero-byte retained publishes. No automated cleanup or
compatibility publication is retained.

### 7. Configure Read-Only Root

The card's `unattended.sh` already applied everything in this section: the
read-only fstab, the tmpfs mounts, the `resolv.conf` handling, and the aliases.
It is kept here as the reference for what that configuration is and why, and for
boards being brought up by hand.

The runtime is compatible with read-only root as long as these paths stay
writable on tmpfs:

- `/tmp`
- `/var/tmp`
- `/var/log`

The native KVS worker keeps the signaling cache in memory and does not depend
on the SDK default `.SignalingCache_v1` file. busybox ntpd keeps no drift file,
so it needs no writable state of its own on a read-only root.

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

`setup-disk -m sys` already wrote a UUID-based fstab with the root ext4 at `/`
and the boot FAT at `/boot`. Reuse those two lines rather than reading `blkid`
and retyping UUIDs: device names change with layout, and the specs already in
the file are known to match the disk the board booted from. Set both to `ro` and
add the tmpfs mounts:

```sh
ROOT_SPEC="$(awk '$2 == "/" && $1 !~ /^#/ { print $1; exit }' /etc/fstab)"
BOOT_SPEC="$(awk '$2 == "/boot" && $1 !~ /^#/ { print $1; exit }' /etc/fstab)"
test -n "$ROOT_SPEC" || echo "no / entry in /etc/fstab"
test -n "$BOOT_SPEC" || echo "no /boot entry in /etc/fstab"
printf 'root=%s\nboot=%s\n' "$ROOT_SPEC" "$BOOT_SPEC"

cp /etc/fstab /etc/fstab.before-ro
cat >/etc/fstab <<EOF
${ROOT_SPEC}  /      ext4  ro,noatime  0 1
${BOOT_SPEC}  /boot  vfat  ro,noatime  0 2
tmpfs  /tmp             tmpfs  nosuid,nodev,mode=1777,size=32M      0 0
tmpfs  /var/tmp         tmpfs  nosuid,nodev,exec,mode=1777,size=96M 0 0
tmpfs  /var/log         tmpfs  nosuid,nodev,mode=0755,size=16M      0 0
EOF
cat /etc/fstab
```

This is the same derivation `unattended.sh` performs, so a board provisioned by
the card and one sealed by hand end up with byte-identical fstabs. Check the
printed `root=` and `boot=` are both `UUID=`-prefixed before continuing: an empty
one means the fstab was not written by `setup-disk` and the new file would mount
nothing.

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
- Unit's hardware worker neutralizes motors internally; supervise-daemon restart
  latency is supervision only, not the motion-control safety layer
- ArduPilot storage, terrain, and logs are under `/var/tmp/txing-cyberbrick-ardupilot/`
  and `/var/log/txing-cyberbrick-ardupilot/`. Both are tmpfs-backed, so content
  from a previous boot does not survive; persistent ArduPilot state is out of
  scope.

### 8. Final Reboot Check

Seal the root, then reboot manually once you are ready to begin the
post-reboot checks:

```sh
root-ro
```

The following generic check is Unit-only. Cyberbrick operators use the
post-reboot checks in [Cyberbrick runtime](#cyberbrick-runtime) instead.

After reconnecting to a Unit board:

```sh
INSTALLS=/root/.local/share/mise/installs

mount | grep ' / '
rc-status default
for s in hardware-worker daemon kvs-master; do
  rc-service txing-${TXING_DEVICE}-$s status
done
for s in hardware-worker daemon kvs-master; do
  echo "== $s"
  tail -n 160 /var/log/txing-${TXING_DEVICE}-$s.log
done
/root/.local/bin/mise list
for b in daemon hardware-worker; do
  "$INSTALLS/txing-${TXING_DEVICE}-$b/latest/txing-${TXING_DEVICE}-$b" --version
done
"$INSTALLS/txing-board-kvs-master/latest/txing-board-kvs-master" --version
readlink /etc/resolv.conf
getent hosts example.com
```

Expected:

- root filesystem is read-only
- `/etc/resolv.conf` points at `/run/resolv.conf` and DNS resolves through
  udhcpc
- the daemon and KVS master start under OpenRC and stay up without a source
  checkout and without network access to GitHub; the KVS master also autostarts
  and completes signaling but stays up only with a camera attached
- the Unit hardware worker is enabled and owns the Unit motor hardware
- the daemon reports version, MQTT connect, and retained board/MCP/video state
  to CloudWatch (its local OpenRC log is empty by design); confirm locally by a
  stable daemon PID and the bound bridge socket
- udev is in the `sysinit` runlevel and `/run/udev` exists after the reboot,
  so libcamera enumerates the camera on a cold boot and not only in the
  session where the modules were loaded by hand

With a camera attached, confirm the full video path end to end:

```sh
KVS="/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master"

rc-service txing-${TXING_DEVICE}-kvs-master stop
"$KVS" --camera-probe
rc-service txing-${TXING_DEVICE}-kvs-master start
grep -E 'TXING_KVS_READY|TXING_KVS_ERROR' /var/log/txing-${TXING_DEVICE}-kvs-master.log
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
rc-status sysinit | grep -i udev
udevadm info --export-db | grep -c '^P:'
LIBCAMERA_LOG_LEVELS=*:DEBUG \
  "/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master" \
  --camera-probe 2>&1 | tail -40
```

| Symptom | Cause | Fix |
| --- | --- | --- |
| No sensor in `dmesg`, no `unicam-image` node | camera is not configured or detected | confirm `usercfg.txt` is included, enable `camera_auto_detect=1`, then use the connected camera's explicit overlay if needed ([step 5](#5-enable-pwm-overlay-and-camera)) |
| `unicam-image` at any number, no `/dev/video11` | `bcm2835-codec` not loaded or board lacks the required encoder | add to `/etc/modules`; a board without `bcm2835-codec-encode` at `video11` is not supported by the current KVS worker |
| Unicam and codec media controllers, no ISP media controller | `bcm2835-isp` not loaded | add to `/etc/modules` ([step 5](#5-enable-pwm-overlay-and-camera)) |
| No `ipa_rpi_vc4.so`, no `vc4/` tuning dir | `libcamera-raspberrypi` missing | the current card's package baseline was not applied; reprovision from a current card |
| All of the above present, no udev services in `sysinit` | no udev daemon, or a daemon with an empty database | confirm the package baseline, then complete [step 2a](#2a-enable-udev) |

**Do not test udev with `ls -d /run/udev`.** It is a false negative: the
directory exists as soon as `udevd` starts, and `rc-service udev status` reports
`started`, while the *database* stays empty until `udev-trigger` replays the
existing devices as uevents. libcamera reads the database, so in that state it
enumerates zero cameras on a board where every check above passes and udev
looks healthy. This is why [Enable Udev](#2a-enable-udev) starts `udev-trigger`
as well as `udev`, and why all three services belong in `sysinit`. The two
checks that do not lie are the runlevel listing — `udev`, `udev-trigger`, and
`udev-settle` all `started` — and the device count from
`udevadm info --export-db`, which is zero or near-zero on an untriggered
database and in the hundreds on a populated one. `rc-service udev-trigger start`
repopulates it immediately, and its `Populating /dev with existing devices
through uevents` line is the fix taking effect.

The debug trace is decisive. `Unable to acquire a Unicam instance` from
`rpi/vc4` means the pipeline handler ran but matched no Unicam media device —
either the sensor/overlay or ISP/tuning pieces are missing, or the enumerator
is empty because udev never populated its database. libcamera may also probe
other pipeline handlers; treat their decline messages as diagnostic noise. The
supported-path test is a successful `--camera-probe`, not a particular
Raspberry Pi model's handler message.

Confirm the media device layer independently of libcamera with `media-ctl`,
which reads the devices directly and does not use udev:

```sh
for m in /dev/media*; do echo "== $m"; media-ctl -d $m -p | head -8; done
```

A healthy supported board shows a `unicam` media controller plus codec and ISP
media controllers. Their device numbers and count vary by board and kernel. If
`media-ctl` shows a working `unicam` while libcamera still enumerates nothing,
the fault is in libcamera's enumeration (`udev` or `libcamera-raspberrypi`),
not in the kernel or the sensor.

### Video Never Reaches READY

If the KVS master logs repeated `GetWorkerConfig failed: ... connect failed`
against the bridge socket, the worker cannot reach the daemon and never gets
as far as the camera. The daemon binds the bridge socket at startup and only
when `video` is in `TXING_DAEMON_CAPABILITIES`:

```sh
grep -E 'CAPABILITIES|SOCKET_PATH' "/root/.config/txing/${TXING_DEVICE}-daemon/daemon.env"
ls -l /run/txing-${TXING_DEVICE}-daemon/ /run/txing-${TXING_DEVICE}-hardware-worker/
pid=$(pgrep -f "txing-${TXING_DEVICE}-daemon" | head -1)
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
rc-service txing-${TXING_DEVICE}-hardware-worker restart
rc-service txing-${TXING_DEVICE}-daemon restart
rc-service txing-${TXING_DEVICE}-kvs-master restart
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
immutable `<device>-vX.Y.Z` release for changed device-specific binaries and a
`kvs-master-vX.Y.Z` release for KVS changes first.

Upgrade the daemon, the hardware worker, and the KVS master together, in one
window, as the `mise upgrade` below does. They speak the device-independent
`txing.board.*` gRPC packages to each other over local sockets, and those
contracts move as a set. A partial upgrade that leaves one binary on an older
release is the worst failure mode this board has: the mismatched pair never
connects, so **video stays down and motion control stops responding with no
local error**. The KVS master retries a bridge that never answers and the
daemon reports the failure to CloudWatch rather than the console, so `rc-status`
shows every service running and the board looks healthy from the console while
being useless. If video or control is missing after an upgrade, record all
three `--version` outputs before investigating anything else. Their versions
can differ because the shared KVS master has its own release stream.

Because the KVS master is dynamically linked against musl and the installed
Alpine libraries, `apk upgrade` and `mise upgrade` happen together in the
same maintenance window: never upgrade the OS packages without moving to the
release built for them, and never install a release built against a newer
Alpine branch than the device runs. Device apk repositories stay on Alpine
`v3.24` until a coordinated bump. The static daemon and hardware worker
depend only on the kernel and are unaffected by apk upgrades.

The **reverse** direction bites on a fresh install rather than an upgrade, and
is the more likely one: a board imaged to current Alpine, installing a release
stream that has not been rebuilt since the last Alpine bump. `latest` resolves
happily and the binary is unrunnable, because the sonames it wants no longer
exist in the branch the board runs. It shows as a wall of
`Error loading shared library` naming *older* sonames than this document
records — a libcamera one revision back on a `v3.24` board that ships
`libcamera.so.0.7`, alongside older grpc, protobuf and abseil revisions.
Retargeting the Alpine contract therefore requires a new shared KVS release.
The fully static device binaries need no rebuild for an Alpine-only change.
Check both relevant streams before installing so the runtime protocol changes
you need are present:

```sh
gh release list --limit 5 | grep "^${TXING_DEVICE}-v"
gh release list --limit 20 | grep '^kvs-master-v'
```

`libstdc++.so.6` or `libgcc_s.so.1` among the missing libraries means something
else: those sonames are stable across Alpine branches, so their absence means
the card's package baseline was not applied, not a release mismatch.

```sh
INSTALLS=/root/.local/share/mise/installs
DAEMON="$INSTALLS/txing-${TXING_DEVICE}-daemon/latest/txing-${TXING_DEVICE}-daemon"
KVS="$INSTALLS/txing-board-kvs-master/latest/txing-board-kvs-master"
WORKER="$INSTALLS/txing-${TXING_DEVICE}-hardware-worker/latest/txing-${TXING_DEVICE}-hardware-worker"

root-rw
apk update
apk upgrade
MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise upgrade \
    txing-${TXING_DEVICE}-daemon \
    txing-board-kvs-master \
    txing-${TXING_DEVICE}-hardware-worker
"$DAEMON" --version
"$KVS" --version
"$WORKER" --version
ldd "$DAEMON"
ldd "$WORKER"
ldd "$KVS" | grep -F "libcamera.so.0.7"
ldd "$KVS" | grep -F "libcamera-base.so.0.7"
sync
```

After the checks pass, reboot manually. Do not reboot if any `ldd` output
reports `not found` or the expected
libcamera sonames are missing; realign the apk branch and the installed
release first, inside the same window.

Cyberbrick upgrades its device release and shared KVS release as one maintenance
set. Do not perform a component-only Cyberbrick upgrade:

```sh
root-rw
MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise upgrade \
    txing-cyberbrick-daemon \
    txing-board-kvs-master \
    txing-cyberbrick-mavlink \
    txing-cyberbrick-ardupilot
for s in ardupilot mavlink daemon kvs-master; do
  rc-service "txing-cyberbrick-$s" restart
done
root-ro
```

After reviewing the service restart results, reboot manually.

The board never clones or patches ArduPilot. If upstream `master` or a tracked
patch breaks the checkout, build, or release job, publish a later Cyberbrick
release and repeat this complete manual upgrade.

Confirm the three binaries speak the current gRPC contracts before rebooting.
Version numbers alone cannot show this: a board can carry matching versions and
still run the superseded per-device packages if it was imaged from an old
release. The package names are embedded in each binary, so `strings` answers it
directly:

```sh
for b in daemon hardware-worker; do
  printf '%s: ' "$b"
  strings "/root/.local/share/mise/installs/txing-${TXING_DEVICE}-$b/latest/txing-${TXING_DEVICE}-$b" \
    | grep -oE 'txing\.(board|unit|cyberbrick)\.(board_video|hardware)\.v1' \
    | sort -u | tr '\n' ' '
  echo
done
printf 'kvs-master: '
strings "/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master" \
  | grep -oE 'txing\.(board|unit|cyberbrick)\.(board_video|hardware)\.v1' \
  | sort -u | tr '\n' ' '
echo
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
KVS workflow container, publish a matching shared KVS release built on that
Alpine version, and only then move the device apk repositories and run the
coupled `apk upgrade` + `mise upgrade` window above.

## Local Development

Daemon and native board worker commands:

```sh
export TXING_DEVICE=cyberbrick      # or: unit

just ${TXING_DEVICE}::board::test
just ${TXING_DEVICE}::board::run
just ${TXING_DEVICE}::board::hardware-test-native
just ${TXING_DEVICE}::board::daemon-build-alpine
just ${TXING_DEVICE}::board::hardware-build-alpine
just ${TXING_DEVICE}::board::nerdctl-build
just ${TXING_DEVICE}::board::nerdctl-smoke
just common::board::kvs-test-native
just common::board::kvs-build-alpine
```

The local daemon uses
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/${TXING_DEVICE}-daemon}`.
Provision that directory with `just aws::cert "$THING_ID"` only when AWS
resource changes are intended.

The `*-build-alpine`, `nerdctl-build`, and `nerdctl-smoke` recipes build and
verify inside pinned aarch64 containers and require `nerdctl` connected to a
native `linux/arm64` containerd environment. They assert the linkage contract
per binary — static daemon and hardware worker (no ELF interpreter),
musl-dynamic KVS master with the
expected libcamera sonames — and `nerdctl-smoke` executes the static pair on
both `debian:trixie` and pinned Alpine and the KVS master on Alpine, the
same gates the release workflow enforces.
## References

- [Board video bridge contract](../contracts/board-video-bridge.md)
- [Hardware worker contract](../contracts/unit-hardware-worker.md)
- [Unit device contracts](../contracts/unit-device-contracts.md)
- [Board operating-system baseline](#operating-system-baseline)
- [Board (Debian, frozen)](./board-debian-frozen.md)
- [Release artifacts](../artifacts.md)
- [Installation](../installation.md)
- [Development](../development.md)
