---
id: doc-23
title: Mac device type architecture
type: specification
created_date: '2026-07-03 07:44'
updated_date: '2026-07-03 19:45'
tags:
  - mac
  - device-type
  - architecture
---
# Mac device type architecture

## Goal

Add a `mac` txing device type that turns the development Mac into a managed end device for local e2e testing. The Mac runs both the rig (`just rig::start <config-dir> true`) and the new mac client (`just mac::start <config-dir>`), registers in AWS IoT, is born as a Sparkplug device under the local rig edge node, accepts REDCON commands 4-1, and at REDCON 1 streams the Mac camera over AWS KVS WebRTC to the office viewer. Dev-only: no systemd units and no release packaging in this scope. A future command-line control milestone builds on the read-only MCP stub introduced here.

## Decisions

- Camera capture/encode: AVFoundation + VideoToolbox (native Objective-C++ capturer, no GStreamer dependency).
- MCP: read-only stub in this scope so the mac REDCON ladder mirrors the unit (`2 = board+mcp`, `1 = board+mcp+video`).
- Rig placement: `mac` devices belong to a new `local` rig type, not `raspi`. A `local` rig is the same three standalone rig daemons registered as a `local` rig thing and run manually on the development Mac via `just rig::start` - no systemd, no autostart, no release install. It is born with `NBIRTH redcon=1` while running and projected `NDEATH` (graceful shutdown or MQTT will) when the process stops.
- Code reuse: copy-and-trim. Go `internal/` packages cannot be imported across modules (`rig/`, `devices/unit/daemon/` are separate modules); `devices/template/README.md` blesses the generic v2 capability wire contract as the integration surface. Consolidating shared daemon code into `devices/common/` is a flagged follow-up once a second consumer stabilizes.

## Device type contract

`devices/mac/manifest.toml`:

- `type = "mac"`, `device_name = "mac"`, `display_name = "Mac"`
- `capabilities = ["sparkplug", "power", "board", "mcp", "video"]` (no ble/thread)
- `compatible_rig_types = ["local"]`, `redcon_command_levels = [4, 3, 2, 1]`
- redcon_rules: `4=[sparkplug]`, `3=[sparkplug,power]`, `2=[sparkplug,power,board,mcp]`, `1=[sparkplug,power,board,mcp,video]`
- `[shadows.<name>]` schema/default for every declared capability (manifest loading fails repo-wide otherwise)
- `[web] adapter = "web/mac-adapter.tsx"`, `[resources.board_video] channel_name = "{device_id}-board-video"`

The type catalog is triple-sourced and all three must stay in sync (registry validation requires the thing `capabilities` attribute to equal the SSM catalog):

1. `devices/mac/manifest.toml`
2. `MacTypeCatalogV2` in `shared/aws/template.yaml` (`Custom::TxingTypeCatalog`, `CatalogBasePath: /txing/town/local/mac`)
3. the device-type tuple in `shared/aws/python/src/aws/type_catalog.py` `build_type_records`

The `local` rig type is declared in `RIG_TYPE_DEFINITIONS` (type_catalog.py), `LocalTypeCatalogV2` (template.yaml), and `shared/aws/thing-type-capabilities.json`; rig certificate bundles for `local` rig things reuse the raspi rig bundle path in `aws_lib.sh`.

Certificate bundles need a `deviceType:mac` dispatch in `shared/aws/scripts/aws_lib.sh` mirroring the unit bundle (TxingDaemonIotPolicy cert, IAM role `txing-daemon-<thing>` including `kinesisvideo:ConnectAsMaster` on `channel/<thing>-board-video/*`, role alias, rendered `devices/mac/daemon.env.template`).

## Runtime shape

`txing-mac-daemon` (new Go module `github.com/mparkachov/txing/devices/mac/daemon`) plays both device roles:

- Watch layer: rig IPC adapter modeled on `txing-thread-connectivity`. Connects to `TXING_RIG_IPC_SOCKET` (default `/tmp/txing-rig/rig-ipc.sock`), consumes inventory, publishes `CapabilityState` (adapterId `dev.txing.mac.Daemon`; `sparkplug`, `power`, `transportRedcon` metric only - it must NOT declare board/mcp/video), handles `CapabilityCommand` for all REDCON 1-4 with `pending -> accepted -> succeeded/failed` results, heartbeats every 10s, republishes state every 30s (TTL 150s).
- Action layer: at simulated power-on, connects to AWS IoT with the device certificate (client id `<thing>-daemon-<pid>` per the TxingDaemonIotPolicy convention; the bare thing name belongs to the rig-owned device session), publishes retained `txings/<id>/capability/v2/state` (adapterId `dev.txing.mac.DaemonBoard`; board/mcp/video, MQTT5 expiry = `TXING_CAPABILITY_TTL_SECONDS`), retained `video/descriptor|status` and `mcp/descriptor|status`, board/mcp/video named-shadow updates, serves the BoardVideoBridge gRPC socket, and supervises the KVS worker (spawn at REDCON 1, SIGTERM on leave, restart with backoff).

Two adapter IDs are required because the rig manager keys evidence by adapterId; one ID would let the IPC transport state and the cloud board state overwrite each other.

### REDCON state machine

Daemon target state S, initial from `TXING_MAC_INITIAL_REDCON` (default 4):

| S | IPC transport state | Action layer | KVS worker | Manager-derived redcon |
|---|---|---|---|---|
| 4 | power:false, transportRedcon:4 | stopped (offline caps published first) | stopped | 4 |
| 3 | power:true, transportRedcon:3 | stopped | stopped | 3 |
| 2 | power:true, transportRedcon:2 | running; board:true, mcp:true, video:false | stopped | 2 |
| 1 | power:true, transportRedcon:1 | running; video follows worker READY | running | 2 -> 1 when READY |

Ordering rule for sleep: stop worker, publish offline caps, stop bridge, disconnect cloud MQTT, then publish the IPC sleep state last so its newer observedAtMs + transportRedcon:4 purges lingering board evidence in the manager. Command success = transition actions complete; video readiness is evidence, not command completion.

## Video worker

Extend `devices/unit/board/kvs_master` with a Darwin lane instead of adding a second worker:

- new AVFoundation/VideoToolbox `VideoCapturer` implementation behind the existing `CreateVideoCapturer()` factory (AVCaptureSession + AVCaptureVideoDataOutput NV12 -> VTCompressionSession H.264 RealTime -> AVCC-to-Annex-B with SPS/PPS on keyframes, keyframe flag from sample attachments, bounded drop-oldest frame queue)
- CMake Darwin branch selecting the capturer and allowing `TXING_KVS_REAL_SDK=ON` + `TXING_KVS_GRPC_BRIDGE=ON`; `PrepareAwsKvsSystemDeps.cmake` gets an APPLE branch resolving Homebrew dylibs (fallback: the SDK's bundled dependency build)
- macOS CA bundle `/etc/ssl/cert.pem` passed via `TXING_KVS_SYSTEM_CA_CERT_PATH`
- the BoardVideoBridge proto stays the single contract source (`devices/unit/proto/txing/unit/board_video/v1/board_video.proto`)

## No rig/witness/base-IAM changes

The rig manager merges adapter states generically, the enlist Lambda creates the thing and the KVS signaling channel from the catalog `resources/boardVideo/channelName`, `TxingDaemonIotPolicy` is thing-variable-scoped, and the office Cognito viewer role already grants `kinesisvideo:ConnectAsViewer`.

## Registration runbook

Once per stack: `just aws::deploy` (ships the `local` rig type, the `mac` thing type, and the SSM catalog).

Once per local rig (the development Mac):

1. `just aws::deploy-rig <town-id> local <rig-name>`
2. `just aws::cert <local-rig-id>`; unpack the rig-daemon config tarball into a local config directory

Once per mac device:

1. `just aws::deploy-device <local-rig-id> mac <name>` (thing + signaling channel)
2. `just aws::cert <mac-thing-id>` (cert bundle + IAM role/alias + rendered daemon.env)
3. `just aws::init-shadow <mac-thing-id>` plus per-shadow inits for power/board/mcp/video

Run: `just rig::start <rig-config-dir> true`, then `just mac::start <mac-config-dir>`.

## Risks

1. KVS WebRTC C SDK on macOS at the pinned commit is unproven: spike first; `TXING_AWS_KVS_WEBRTC_SDK_GIT_TAG` stays overridable; bundled-dependency build is the fallback.
2. Camera TCC for detached processes: a foreground `camera-probe` recipe triggers the permission prompt once per terminal app; worker errors surface in retained `video/status.lastError`.
3. VideoToolbox access-unit formatting (Annex-B, SPS/PPS on IDR, monotonic timestamps): debug hexdump of the first AU; match the libcamera capturer invariants.
4. Copied protocol drift vs rig schema 2.0: pin source files in comments and add wire-format golden tests against captured rig payloads.

## Non-goals

Actuator MCP tools and the command-line control surface, systemd/release packaging for the mac client, changes to rig/witness/office video internals, and consolidation of shared daemon code into `devices/common/`.

## GitHub issue references

- [#61 — Milestone: Mac end-device client](https://github.com/mparkachov/txing/issues/61) (migrated from `TASK-22`)
- [#63 — mac catalog and UI contract is first-class](https://github.com/mparkachov/txing/issues/63) (migrated from `TASK-22.1`)
- [#65 — txing-mac-daemon joins the rig and converges REDCON 4-3](https://github.com/mparkachov/txing/issues/65) (migrated from `TASK-22.2`)
- [#67 — mac daemon action layer reaches REDCON 2 with board and MCP stub](https://github.com/mparkachov/txing/issues/67) (migrated from `TASK-22.3`)
- [#69 — KVS worker streams the Mac camera on macOS](https://github.com/mparkachov/txing/issues/69) (migrated from `TASK-22.4`)
- [#71 — mac device reaches REDCON 1 with office-visible video](https://github.com/mparkachov/txing/issues/71) (migrated from `TASK-22.5`)
- [#73 — mac devices belong to a new local rig type](https://github.com/mparkachov/txing/issues/73) (migrated from `TASK-22.6`)
- [#74 — local rig start defaults to manager-only with implicit config dir](https://github.com/mparkachov/txing/issues/74) (migrated from `TASK-22.7`)
