---
id: doc-36
title: Cyberbrick MAVLink WebRTC control architecture
type: specification
created_date: '2026-08-11 09:55'
updated_date: '2026-08-11 09:55'
tags:
  - cyberbrick
  - mavlink
  - webrtc
  - ardupilot
  - board
  - office
---

# Cyberbrick MAVLink WebRTC control architecture

## Outcome and scope

Cyberbrick replaces its MCP and hardware-worker control path with an end-to-end
MAVLink capability. ArduPilot remains the sole owner of the existing PWM0/1 ESC
outputs, a new supervised board component brokers its local MAVLink transport,
and Office controls and observes the flight controller through a WebRTC data
channel. Unit retains its existing MCP capability, hardware worker, and control
behavior.

This design supersedes the Cyberbrick-specific no-integration and trusted-LAN
MAVLink runtime assumptions in `doc-34` and `doc-35`. Those documents remain the
historical contract for the completed ArduPilot installation milestone.

The video and control paths use separate KVS signaling channels and peer
connections:

- `<thing>-board-video` carries video only.
- `<thing>-mavlink` carries MAVLink data only and works without a camera or
  video session.

One `txing-cyberbrick-kvs-master` process owns both paths, but their credentials,
signaling, peers, retry loops, and failure state are isolated. Camera
initialization or video signaling failure cannot stop MAVLink control.

## Component ownership

`txing-cyberbrick-mavlink` is a new bounded, supervised OpenRC service. It owns
the local flight-controller transport and exposes
`txing.board.mavlink.v1.BoardMavlink` at
`/run/txing-cyberbrick-mavlink/cyberbrick-mavlink.sock`:

- `GetStatus` reports transport state, heartbeat freshness, flight-controller
  system and component IDs, armed state, mode, MAVLink protocol version, and
  current errors.
- `Exchange` is a bidirectional stream of complete MAVLink frames.
- `EnterSafeState` requests neutral control and Hold, and may request disarm
  during shutdown.

The service accepts `TXING_MAVLINK_FC_ENDPOINT`. Version 1 implements
`udp://127.0.0.1:14550` behind a transport interface. The URI contract reserves
`serial:///dev/...?baud=...` for a later UART transport without changing the
daemon, KVS, or Office interfaces.

The board daemon remains the sole authority for active-session ownership,
actor identity, epoch changes, takeover, lease expiry, REDCON derivation, and
cloud publication. Its existing Unix gRPC server adds
`txing.board.mavlink_bridge.v1.BoardMavlinkBridge`. The KVS master uses this
interface for control-channel configuration, temporary credentials, peer
lifecycle, text control messages, and binary MAVLink frame exchange.

The KVS master conditionally starts the data-only control connection when the
device manifest contains `mavlink`. Its video connection remains independently
conditional on the existing video configuration. Cyberbrick initializes the
MAVLink service and bridge but does not initialize an MCP hardware client. Unit
initializes the existing MCP hardware path and does not initialize MAVLink.

## MAVLink and WebRTC wire contracts

The data-only peer connection has one ordered, reliable RTCDataChannel labeled
`txing.mavlink.v1`.

Binary messages contain exactly one complete, unsigned MAVLink 2 frame. Board
and Office code do not rewrite sequence numbers, system IDs, component IDs,
payloads, or checksums. Frames with invalid framing or CRC, signed frames, and
messages outside the supported common dialect are rejected.

Text messages are JSON request and response envelopes for:

- `control.get_state`
- `control.activate`
- `control.renew_active`
- `control.release_active`

Requests carry a request ID and actor where applicable. Activation also carries
a takeover flag. State and successful mutation responses carry the active
epoch and the five-second lease TTL. Errors use stable structured codes for
busy ownership, stale epoch, and invalid requests.

All accepted flight-controller telemetry is broadcast to every connected
observer. Each peer has a bounded outbound buffer; a slow observer drops or is
closed according to the bridge policy without blocking the flight-controller
reader or other peers.

Only the active session and current epoch may send uplink frames. The daemon
allows only GCS `HEARTBEAT`, `MANUAL_CONTROL`, non-forced
`MAV_CMD_COMPONENT_ARM_DISARM`, and commands that select Manual or Hold mode.
It rejects mission, parameter, reboot, arbitrary command, invalid-source,
wrong-target, forced arm/disarm, inactive-session, and stale-epoch traffic.

Generated MAVLink 2 common-dialect bindings for the board's C/C++ boundary and
Office TypeScript are vendored from pinned upstream definitions and tooling.
Their provenance and licenses are tracked, regeneration is reproducible, and
golden-frame tests cover framing and CRC compatibility. Office gains no runtime
MAVLink package dependency.

## Session, control, and safety behavior

Observers may connect concurrently, but one session/epoch owns control. An
activation creates or renews a five-second lease. Explicit takeover changes the
owner and epoch atomically; frames from the old epoch fail immediately. The
handoff does not inject neutral or Hold. The previous setpoint can persist only
until the independent control watchdog expires.

While actively driving, Office sends fresh `MANUAL_CONTROL` at 10 Hz. A detected
active data-channel close triggers safe control immediately. Otherwise, 500 ms
without an accepted control packet sends neutral and requests Rover Hold while
leaving it armed. ArduPilot's one-second GCS failsafe provides a secondary Hold.

Only the active owner may arm or disarm. Arm sends an ordinary, non-forced
command and is complete only after `COMMAND_ACK` and an armed heartbeat. Disarm
uses the same acknowledgement and state-confirmation rule and is sent
immediately. No force-arm/disarm magic value or blanket arming-check bypass is
permitted.

Office maps left/right to ArduRover `MANUAL_CONTROL.y`, forward/reverse to
`.z`, and marks unused axes invalid. It preserves neutral on stop, blur, and
page hide. Observation, control acquisition, and arm state remain distinct UI
states.

On REDCON4 or shutdown, the daemon requests `EnterSafeState`: neutral, Hold,
and disarm are attempted before halt. This is a bounded best-effort sequence;
the design makes no new crash-time guarantee beyond existing ArduPilot,
sysfs-PWM, and ESC behavior.

## Capability, cloud, and REDCON contracts

Cyberbrick manifests, shadows, topics, and catalogs replace `mcp` with
`mavlink`. Validation rejects a device declaring both capabilities. Unit keeps
`mcp` unchanged.

The MAVLink capability publishes:

- `txings/<thing>/mavlink/descriptor`, retained without expiry.
- `txings/<thing>/mavlink/status`, retained with the normal capability TTL.
- A `mavlink` named shadow containing link, target, armed/mode, peers,
  active-control, and error state, without generic timestamp fields.
- `resources.mavlink.channelName` in the device catalog.

`capability.mavlink=true` means the local service is healthy, a fresh
flight-controller heartbeat exists, and the control KVS master is ready. It
does not require an Office peer.

Inventory adds an internal boolean metric rule named `mavlinkArmed`. It is not
published as a capability. Cyberbrick REDCON derives as follows:

| State | REDCON |
| --- | --- |
| Board powered, MAVLink unavailable | 3 |
| MAVLink ready and disarmed, with or without video | 2 |
| MAVLink ready and armed, without video | 2 |
| MAVLink ready, armed, and video ready | 1 |

Disarming a healthy video-connected device therefore changes REDCON1 to
REDCON2. A REDCON1 command starts the stack and video but never arms the rover.
REDCON4 invokes the safe-state shutdown sequence.

Cloud enlistment and catalog tooling create and validate `<thing>-mavlink`, add
it to the device credential policy alongside `<thing>-board-video`, and preserve
the existing Office viewer authorization model.

## ArduPilot, release, and rollout

ArduPilot changes SERIAL0 to `udpin:127.0.0.1:14550`. A tracked ArduRover
defaults file is packaged with the executable and loaded on every tmpfs-backed
boot. It selects MAVLink 2, GCS system ID 255, Manual/Hold control, left/right
throttle output functions, the existing consumer ESC pulse ranges, GCS Hold
failsafe with a one-second backup timeout, no RC receiver, and only the minimum
target-specific arming accommodations.

ArduPilot directly owns PWM0/1. Cyberbrick adds no direction GPIO, 20 kHz
H-bridge behavior, or compatibility path through the old hardware worker.

Cyberbrick releases add
`txing-cyberbrick-mavlink-linux-aarch64.tar.gz`, include the ArduPilot defaults
beside its executable, and stop publishing or installing the Cyberbrick
hardware-worker artifact. Unit release assets remain unchanged. The default
OpenRC dependency order is ArduPilot, MAVLink, daemon, then KVS master; the
Cyberbrick hardware worker is stopped and removed.

Rollout is forward-only and manual:

1. Provision the MAVLink KVS resource and IAM policy.
2. During a writable-root window, upgrade all Cyberbrick binaries and the
   ArduPilot executable/defaults together.
3. Replace OpenRC and configuration files, disable the hardware worker, and
   reboot with the root read-only.
4. Deploy Office.
5. Manually remove the obsolete Cyberbrick MCP named shadow and retained MCP
   descriptor/status messages.

There is no automated cleanup, dual publishing, compatibility shim, or rollback
to the old Cyberbrick control contract.

## Validation and physical acceptance

Automated coverage includes generated binding vectors, CRC and framing; UDP
reconnect and heartbeat freshness; uplink filtering; lease, epoch, and takeover;
the 500 ms safe-control watchdog; multi-observer broadcast and slow-peer
isolation; independent video/control failures; credential refresh; capability,
shadow, catalog, and REDCON projections; and unchanged Unit MCP behavior.

Office coverage includes data-only negotiation without a video transceiver,
observer-only operation, active-only arm/disarm with acknowledgement, Rover
`y/z` mapping, 10 Hz refresh, neutral on stop/blur/page-hide, and seamless
takeover.

Physical acceptance is operator-run with the Cyberbrick lifted and motor power
initially isolated. It verifies read-only-root reboot and OpenRC health,
hardware-worker removal, data-only telemetry/control during camera failure,
video plus arming to REDCON1, existing ESC/PWM forward/reverse/turn/neutral and
disarm behavior, concurrent observation and takeover, and neutral/Hold within
500 ms after an active connection interruption while the rover remains armed.

## Explicit non-goals

- UART transport implementation.
- A supported agent or CLI MAVLink client.
- MAVLink signing.
- Missions, parameter editing, or autonomous control.
- Video storage.
- Compatibility with Cyberbrick's former MCP control path.
- New motor electronics.
- Additional crash-time safety guarantees.

## GitHub tracking

- [Milestone 2 — Cyberbrick MAVLink WebRTC control](https://github.com/mparkachov/txing/milestone/2)
- [#114 — Define Cyberbrick MAVLink capability contracts](https://github.com/mparkachov/txing/issues/114)
- [#115 — Provision Cyberbrick MAVLink signaling and lifecycle state](https://github.com/mparkachov/txing/issues/115)
- [#116 — Run Cyberbrick MAVLink control through the board runtime](https://github.com/mparkachov/txing/issues/116)
- [#117 — Control Cyberbrick over MAVLink from Office](https://github.com/mparkachov/txing/issues/117)
- [#118 — Ship Cyberbrick ArduPilot and MAVLink services together](https://github.com/mparkachov/txing/issues/118)
- [#119 — Validate Cyberbrick MAVLink control on physical hardware](https://github.com/mparkachov/txing/issues/119)
