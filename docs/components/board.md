# Board

The board is the device-side Raspberry Pi. It is power-switched by the MCU, publishes board runtime state, supervises the native KVS sender, and exposes the board MCP surface.

## Responsibilities

- publish the `board` named shadow
- publish the `video` named shadow
- publish retained video descriptor and status topics under `txings/<device_id>/video/*`
- publish retained MCP descriptor and status topics under `txings/<device_id>/mcp/*`
- publish retained v2 capability state for `board`, `mcp`, and `video` for direct SparkplugManager consumption
- supervise the native KVS WebRTC sender as a child process
- subscribe to Sparkplug `DCMD.redcon` and halt locally on `redcon=4`
- enforce MCP lease ownership for motion control

The stable Rust unit daemon owns `board.*` Thing Shadow updates and the retained
board/MCP/video capability state. The older Python `txing-board` runtime remains
in the repository for legacy and development reference only.

## Current Interfaces

### Board Shadow

The board-owned named shadow is:

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

- `reported.power=false` is best-effort clean shutdown state only
- stale `power=true` or `wifi.online=true` must not be treated as authoritative after a hard power cut

### Video

Current video is headless AWS KVS WebRTC:

- signaling channel: `<device_id>-board-video`
- browser route: `/<town>/<rig>/<device>/video`
- retained topics: `txings/<device_id>/video/descriptor` and `txings/<device_id>/video/status`
- capability state: `txings/<device_id>/capability/v2/state`

The board video contract is documented in
[devices/unit/docs/board-video.md](../../devices/unit/docs/board-video.md).

### MCP

Current MCP transport:

- retained descriptor topic: `txings/<device_id>/mcp/descriptor`
- retained status topic: `txings/<device_id>/mcp/status`
- current stable transport: MQTT JSON-RPC
- deferred transport: WebRTC data channel on the board video KVS session with label `txing.mcp.v1`

Current tool surface:

- `control.acquire_lease`
- `control.renew_lease`
- `control.release_lease`
- `cmd_vel.publish`
- `cmd_vel.stop`
- `robot.get_state`

`robot.get_state` is the current read surface for lease, motion, and video runtime state. Those live runtime fields are no longer carried in Thing Shadow.

## Local Runtime State

The stable Rust daemon writes no persistent board runtime state outside its
per-user config directory. Feature-channel mise installs use `/var/tmp`.

The legacy Python board runtime writes transient local state only:

- `/tmp/txing_board_shadow.json`
- `/tmp/txing_board_video_state.json`
- `/tmp/txing_board_mcp_webrtc.sock`

This is why the read-only-rootfs setup keeps `/tmp` and `/var/tmp` on tmpfs. The native sender also keeps the KVS signaling cache in memory only.

## Build And Run

Rust unit daemon local run:

```bash
just unit::daemon::run
```

For local development, the daemon uses the per-user config directory
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}`.
On deployed boards the stable runtime is root-owned and uses
`/root/.config/txing/unit-daemon`. Its `daemon.env` file is sourceable and the IoT
certificate files live beside it. In the current implementation, the daemon
publishes the `board`, `mcp`, and `video` runtime surfaces for web/Sparkplug
visibility while keeping MCP MQTT-only.

Provision daemon config and certs only when AWS resource changes are intended:

```bash
just unit::cert <thing-id>
```

Legacy Python board runtime commands:

```bash
just unit::board::check
just unit::board::submodules
just unit::board::build-native
just unit::board::build
just unit::board::run
just unit::board::once
```

`build-native` builds the native sender against the shared AWS KVS WebRTC SDK
submodule under `devices/common/board/`. Initialize it with
`just unit::board::submodules` before the first native build. Third-party KVS
dependencies come from distro packages, not from the SDK's bundled source
builds.

Manual motor bring-up:

```bash
just unit::board::motor-raw 240 240
just unit::board::motor-stop
```

## Service Install

The current stable service uses the root-owned Rust daemon installer:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh -o /tmp/txing-install-systemd.sh
bash /tmp/txing-install-systemd.sh stable
```

The legacy Python board service path is still available for development
comparison and must run as `root`:

```bash
just unit::board::install-service "$BOARD_VIDEO_SENDER_COMMAND"
sudo journalctl -u board -f
```

The generated unit:

- loads `config/aws.env`
- enables `NetworkManager-wait-online.service`
- waits for time synchronization before starting the AWS-backed sender
- starts `board` with `--heartbeat-seconds 60`

Board host setup, including the read-only root filesystem layout, lives in [installation.md](../installation.md).
