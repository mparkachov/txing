# Board

The board is the device-side Raspberry Pi. It is power-switched by the MCU, publishes board runtime state, supervises the native KVS sender, and exposes the board MCP surface.

## Responsibilities

- publish the `board` named shadow
- publish the `video` named shadow
- publish retained video descriptor and status topics under `txings/<device_id>/video/*`
- publish retained MCP descriptor and status topics under `txings/<device_id>/mcp/*`
- supervise the native KVS WebRTC sender as a child process
- subscribe to Sparkplug `DCMD.redcon` and halt locally on `redcon=4`
- enforce MCP lease ownership for motion control

`txing-board` remains the only publisher of `board.*` Thing Shadow updates.

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

The board video contract is documented in
[devices/unit/docs/board-video.md](../../devices/unit/docs/board-video.md).

### MCP

Current MCP transport:

- retained descriptor topic: `txings/<device_id>/mcp/descriptor`
- retained status topic: `txings/<device_id>/mcp/status`
- mandatory fallback transport: MQTT JSON-RPC
- optional higher-priority transport: WebRTC data channel on the board video KVS session with label `txing.mcp.v1`

Current tool surface:

- `control.acquire_lease`
- `control.renew_lease`
- `control.release_lease`
- `cmd_vel.publish`
- `cmd_vel.stop`
- `robot.get_state`

`robot.get_state` is the current read surface for lease, motion, and video runtime state. Those live runtime fields are no longer carried in Thing Shadow.

## Local Runtime State

The board runtime writes transient local state only:

- `/tmp/txing_board_shadow.json`
- `/tmp/txing_board_video_state.json`
- `/tmp/txing_board_mcp_webrtc.sock`

This is why the read-only-rootfs setup keeps `/tmp` and `/var/tmp` on tmpfs. The native sender also keeps the KVS signaling cache in memory only.

## Build And Run

```bash
just board::check
just board::build-native
just board::build
just board::run
just board::once
```

Manual motor bring-up:

```bash
just board::motor-raw 240 240
just board::motor-stop
```

## Service Install

The service must run as `root`.

```bash
just board::install-service "$BOARD_VIDEO_SENDER_COMMAND"
sudo journalctl -u board -f
```

The generated unit:

- loads `config/aws.env`
- enables `NetworkManager-wait-online.service`
- waits for time synchronization before starting the AWS-backed sender
- starts `board` with `--heartbeat-seconds 60`

Board host setup, including the read-only root filesystem layout, lives in [installation.md](../installation.md).
