# devices/mac

`mac` is a development-only txing device type that turns the local macOS
development machine into a managed end device for e2e testing. `mac` devices
belong to a `local` rig: the same standalone rig runtime as a `raspi` rig,
registered as a `local` rig thing and started manually on the Mac with
`just rig::start` (sparkplug manager only, config from
`~/.config/txing/rig-daemon`; no systemd, no autostart). The Mac runs
the `local` rig and the mac client side by side: the device registers in AWS
IoT, is born as a Sparkplug device under the local rig edge node, accepts
REDCON commands 4-1, and at REDCON 1 streams the Mac camera over AWS KVS
WebRTC to the office viewer. The `local` rig edge node itself is born at
REDCON 1 while `just rig::start` runs and is projected `NDEATH` as soon as the
processes stop.

There is no MCU watch layer and no BLE/Thread transport. The mac daemon plays
both device roles:

- Watch layer: a rig IPC connectivity adapter (generic v2 capability contract)
  that publishes `sparkplug`/`power` evidence with a `transportRedcon` metric
  and accepts all REDCON targets 1-4.
- Action layer: board-style retained cloud topics (`txings/<id>/capability/v2/state`,
  `video/*`, `mcp/*`), board/mcp/video named shadows, the BoardVideoBridge gRPC
  socket, and supervision of the KVS video worker.

REDCON ladder (per `manifest.toml`):

- `4 = [sparkplug]` - asleep; only the IPC adapter reports.
- `3 = [sparkplug, power]` - simulated power on.
- `2 = [sparkplug, power, board, mcp]` - action layer up, read-only MCP stub.
- `1 = [sparkplug, power, board, mcp, video]` - KVS worker streams the Mac camera.

Layout:

- `manifest.toml`: device type contract (capabilities, redcon rules, shadows,
  web adapter, board video channel resource)
- `aws/`: per-shadow schema and default payloads
- `web/`: office SPA adapter (video at REDCON 1, no drive control)
- `daemon.env.template`: runtime config rendered by `just aws::cert <thing-id>`
- `daemon/`: `txing-mac-daemon` Go runtime

Run the daemon from the repository checkout:

```bash
just mac::test
just mac::start          # config from TXING_MAC_CONFIG_DIR or ~/.config/txing/mac-daemon
just mac::log
just mac::restart
just mac::stop
just mac::check          # build + config dry-run
```

`just mac::start <config-dir>` selects an explicit config directory. The
daemon needs at least `TXING_THING_ID` in `daemon.env` (the registered mac
thing name); process environment values take precedence over `daemon.env`,
so unset stray `TXING_THING_ID` exports before starting. Logs and the PID
file live under `/tmp/txing-mac` (`TXING_MAC_RUN_DIR` overrides).

The watch layer connects to the rig IPC socket (`TXING_RIG_IPC_SOCKET`,
default `/tmp/txing-rig/rig-ipc.sock` on macOS), waits for the retained rig
inventory to include the thing, and then publishes capability state
(adapter id `dev.txing.mac.Daemon`): `sparkplug` always, `power` below
REDCON 4, and the `transportRedcon` metric. All REDCON targets 1-4 are
accepted; a command succeeds once the target is applied locally, and the
reported REDCON converges to the highest level supported by published
evidence. The daemon reconnects if the rig restarts, and the rig projects
DDEATH within the capability TTL after the daemon stops.

At REDCON 2 and 1 the daemon also runs the action layer (adapter id
`dev.txing.mac.DaemonBoard`): its own AWS IoT MQTT session with client id
`<thing>-daemon-<pid>`, retained `txings/<thing>/capability/v2/state`
(board/mcp true, video following worker readiness), retained MCP and video
descriptor/status topics, board/mcp/video named-shadow updates, the
BoardVideoBridge gRPC socket (`TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH`,
default `/tmp/txing-mac/board-video-bridge.sock`), and a read-only MCP
stub over mqtt-jsonrpc sessions (`control.get_state`, `robot.get_state`;
no actuator tools yet). Leaving REDCON 2 publishes the offline states
before the watch layer reports the lower level, so no stale board
evidence survives.

The action layer requires the device certificate bundle: run
`just aws::cert <thing-id>` on the operator machine and unpack
`certs/<thing-id>/<thing-id>-daemon-config.tgz` into
`~/.config/txing/mac-daemon`. Without those settings the daemon runs
watch-layer only (REDCON tops out at 3) and logs a warning when 2 or 1
is commanded.

Video comes from the shared unit KVS worker built natively for macOS:

```bash
just mac::kvs-build       # real KVS SDK + gRPC bridge; Homebrew deps preflight
just mac::camera-probe    # foreground capture-only run; grants the camera TCC prompt
```

`kvs-build` compiles `devices/unit/board/kvs_master` into
`devices/unit/board/kvs_master/build-macos/txing-unit-kvs-master` with the
AVFoundation + VideoToolbox capturer (Annex-B H.264, SPS/PPS on keyframes).
It needs the Homebrew formulas `openssl@3 libwebsockets srtp libusrsctp
log4cplus protobuf grpc`; the recipe lists anything missing. Run
`camera-probe` once from a foreground terminal before any detached start:
macOS attributes camera permission to the terminal application, and a
detached worker whose prompt cannot be shown is denied silently. The probe
exits nonzero with a `TXING_KVS_ERROR` marker when access is denied or no
frames arrive.

At REDCON 1 the daemon supervises the worker itself (there is no systemd
on the mac device): it spawns `TXING_KVS_MASTER_COMMAND` with the bridge
socket argument, and `just mac::start` defaults that variable to the
`kvs-build` output so a repo checkout works with an unedited cert bundle.
The worker fetches channel, region, and credentials over the bridge and
reports readiness back; video becomes ready and reported REDCON converges
to 1. Leaving REDCON 1 sends the worker SIGTERM (SIGKILL after 5s), so
the camera indicator is only lit at REDCON 1. If the worker dies, the
daemon publishes a visible video error (reported REDCON degrades to 2),
then restarts it with 1s-30s backoff until it recovers. Worker output goes
to `/tmp/txing-mac/txing-unit-kvs-master.log`. For debugging, the worker
can still be run manually in the foreground against the bridge socket
while the daemon holds REDCON 2.

## Runbook

One-time registration (operator machine):

1. `just aws::deploy` - ships the `mac` thing type and SSM catalog (once
   per account).
2. `just aws::deploy-device <local-rig-id> mac <name>` - creates the
   thing (`mac-<shortId>`) and its KVS signaling channel
   `<thing>-board-video`.
3. `just aws::cert <thing-id>` - cert bundle + IAM role/alias; unpack
   `certs/<thing-id>/<thing-id>-daemon-config.tgz` into
   `~/.config/txing/mac-daemon`.
4. `just mac::kvs-build`, then `just mac::camera-probe` from a foreground
   terminal (grant the camera prompt).

Operation:

1. `just rig::start` (local rig), then `just mac::start`.
2. Command the ladder from office: 4 sleep, 3 power, 2 board+MCP,
   1 board+MCP+video. At 1 the worker is spawned automatically and the
   office video route shows the live camera.
3. Command 2 (or 3/4) to stop the stream; the camera indicator turns off
   before the lower level is reported.
4. `just mac::stop` terminates the worker, publishes the offline states,
   and the rig projects DDEATH immediately.

Failure behavior: a worker crash at REDCON 1 surfaces as a video error
and REDCON 2 until the automatic restart recovers; a rig restart is
survived via IPC reconnect without losing the posture; an unclean daemon
kill falls back to DDEATH within the 150s capability TTL, and the
retained cloud topics carry MQTT5 message expiry so no stale ready video
status outlives the daemon.

Design and milestone context:

- `backlog/docs/architecture/mac-device-type/`
- `backlog/docs/milestones/mac-device-type/`

This device type is dev-only: no systemd units and no release packaging.
