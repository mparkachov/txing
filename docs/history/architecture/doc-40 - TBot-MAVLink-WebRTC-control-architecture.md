---
id: doc-40
title: TBot MAVLink WebRTC control architecture
type: specification
created_date: '2026-08-31 22:44'
updated_date: '2026-08-31 22:44'
tags:
  - tbot
  - mavlink
  - webrtc
  - ardupilot
  - board
  - office
---

# TBot MAVLink WebRTC control architecture

## Outcome and relationship to existing designs

TBot replaces its MCP and hardware-worker control path with the MAVLink-over-
WebRTC architecture already implemented for Cyberbrick. ArduPilot becomes the
exclusive owner of TBot's existing DRV8835 PWM and direction outputs. Office
observes and controls it through an independent data-only WebRTC peer while
the existing board-video peer continues to carry video.

The Cyberbrick implementation in `doc-36` and `doc-37` is the completed
foundation and keeps its current runtime and public behavior. The TBot
ArduPilot proof of concept in `doc-38` and `doc-39` establishes the motor and
flight-controller baseline. This design supersedes only that proof of
concept's TBot-specific optional-service, manual-owner-transfer, and trusted-
LAN UDP assumptions.

Unit and all other device types keep their existing capabilities, releases,
runtime ownership, Office behavior, and cloud contracts.

## Shared MAVLink contract

The device-neutral MAVLink definitions and generated bindings move from
Cyberbrick ownership into the shared board implementation. Their public
contracts do not change:

- `txing.board.mavlink.v1.BoardMavlink` remains the local flight-controller
  transport API.
- `txing.board.mavlink_bridge.v1.BoardMavlinkBridge` remains the daemon-owned
  WebRTC bridge API.
- The ordered, reliable data channel remains `txing.mavlink.v1`.
- Binary messages remain one complete unsigned MAVLink 2 common-dialect frame.
- JSON messages remain limited to `control.get_state`, `control.activate`,
  `control.renew_active`, and `control.release_active` with the existing
  request, response, error, lease, and epoch semantics.
- Existing Cyberbrick protobuf packages, wire values, descriptor values,
  generated vectors, and Office behavior remain compatible.

The active-control lease remains five seconds. Multiple peers may observe, but
only the current session and epoch may transmit. Explicit takeover is atomic,
and the uplink allowlist remains GCS heartbeat, `MANUAL_CONTROL`, ordinary
non-forced arm/disarm, and Manual/Hold selection.

## TBot runtime ownership

TBot declares `mavlink` instead of `mcp`. It no longer publishes, installs, or
starts a TBot hardware worker. There is no fallback, feature flag, dual control
path, or automatic owner switch; ArduPilot is the sole motor-hardware owner.

`txing-tbot-mavlink` runs as an independently supervised OpenRC service and
owns the local flight-controller transport at
`udp://127.0.0.1:14550`. It serves the local socket
`/run/txing-tbot-mavlink/tbot-mavlink.sock`. The TBot daemon exposes its
MAVLink bridge at `/run/txing-tbot-daemon/mavlink-bridge.sock`.

Linux reserves ArduPilot `SERIAL0` for the process console, so TBot keeps
MAVLink 2 on `SERIAL1` and starts ArduRover with
`--serial1 udpin:127.0.0.1:14550`. The former
`udpin:0.0.0.0:14550` trusted-LAN endpoint is removed.

The default OpenRC order is:

1. `txing-tbot-ardupilot`
2. `txing-tbot-mavlink`
3. `txing-tbot-daemon`
4. `txing-tbot-kvs-master`

All four are boot-enabled. The KVS master starts its MAVLink data-only loop
before camera setup and keeps the video and control credentials, signaling,
peers, retries, and health independent.

## DRV8835 and safety behavior

The validated TBot ArduPilot hardware contract remains unchanged:

- `MOT_PWM_TYPE=3` uses upstream brushed-with-relay behavior.
- `SERVO1_FUNCTION=73` and `SERVO2_FUNCTION=74` drive PWM chip 0 channels 0
  and 1.
- Relay reverse functions drive physical BCM GPIO 5 and 6.
- `MOT_PWM_FREQ` remains unset, retaining the upstream 16 kHz default and
  supported MAVLink configurability after restart.
- The one-second GCS Hold failsafe remains configured.
- The no-sensor Linux target retains its existing TBot arming-check
  accommodation, but Office sends only ordinary non-forced arm/disarm.

Office sends `MANUAL_CONTROL` at 10 Hz while driving. An active channel close
requests neutral and Hold immediately; otherwise 500 ms without an accepted
active control frame requests neutral and Hold while leaving the rover armed.
REDCON4 and graceful daemon shutdown make bounded neutral, Hold, and ordinary
disarm attempts. No stronger hard-crash guarantee is claimed.

## Capability, cloud, and REDCON contracts

TBot's capability profile becomes `sparkplug`, `thread`, `power`, `board`,
`mavlink`, and `video`. Its manifest, catalog, schemas, defaults, topics, and
named shadows remove MCP and add MAVLink plus
`resources.mavlink.channelName=<thing>-mavlink`.

The initial `mavlinkArmed` REDCON1 metric requirement is superseded by
[doc-42](doc-42%20-%20MAVLink-video-readiness-independent-of-arming.md).
TBot REDCON is:

| State | REDCON |
| --- | --- |
| Board powered, MAVLink unavailable | 3 |
| MAVLink ready, with or without arming, without video | 2 |
| MAVLink ready, with or without arming, and video ready | 1 |

A REDCON1 request starts the required runtime and video but never arms the
rover. Disarming a healthy video-connected TBot leaves it at REDCON1.

Enlistment creates and validates `<thing>-mavlink`. The TBot board credential
role authorizes master access to both its board-video and MAVLink channels.
Office retains its existing viewer-only authorization model.

## Office behavior

The existing Cyberbrick MAVLink session and control panel become a shared
Office capability. TBot uses the same connection, observation, control lease,
takeover, acknowledgement-confirmed arm/disarm, Manual/Hold, arrow-key drive,
and neutral behavior while retaining TBot naming and Thread connectivity
presentation.

At REDCON2, Office can open the TBot detail view and establish MAVLink control
without video. At REDCON1 it also displays the independent board-video peer,
whether the flight controller is armed or disarmed.
Camera or video signaling failure must not close, restart, or disable the
MAVLink peer.

## Release and forward-only rollout

The TBot release adds `txing-tbot-mavlink-linux-aarch64.tar.gz`, keeps the
ArduPilot binary/defaults and corresponding-source assets, and stops publishing
`txing-tbot-hardware-worker-linux-aarch64.tar.gz`. The next available TBot and
Office patch versions are used; at planning closeout these are TBot `0.18.7`
and Office `0.17.1`. The existing KVS master `0.18.1` is sufficient unless its
binary changes during implementation.

Rollout is coordinated and forward-only:

1. Apply the updated catalog and IAM policy, re-enlist TBot, and create a fresh
   board certificate/configuration bundle.
2. In one writable-root maintenance window, upgrade TBot and KVS artifacts,
   replace configuration and OpenRC files, remove the hardware-worker service,
   and enable the four-service MAVLink stack.
3. Reboot with the root read-only and validate the board runtime.
4. Deploy Office.
5. Manually remove obsolete TBot MCP retained messages and named shadow.

There is no dual publication, compatibility shim, automated cleanup, or
rollback framework.

## Validation and exit criteria

Automated validation covers shared protocol vectors and regeneration, TBot
manifest and schemas, catalog/IAM/enlistment, REDCON projection, daemon and KVS
control isolation, lease/epoch/allowlist/watchdog behavior, Office operation,
release archive shape, OpenRC policy, and unchanged Cyberbrick and Unit tests.

Physical acceptance is operator-run with the TBot lifted and motor power
initially isolated. It verifies read-only reboot, exclusive ArduPilot
ownership, loopback-only MAVLink, telemetry without video, ordinary arming,
REDCON1 video, track movement and neutral/disarm, camera-failure independence,
multi-observer takeover, and neutral/Hold within 500 ms after active WebRTC
loss. The prior proof-of-concept exception for an unperformed link-loss test is
not inherited; the milestone remains open until this test passes.

## Explicit non-goals

- Changes to Cyberbrick, Unit, or another device type's public behavior.
- TBot MCP or hardware-worker compatibility.
- Direct QGroundControl or other trusted-LAN MAVLink access.
- UART transport, MAVLink signing, missions, parameters, or autonomy.
- New motor electronics, PWM semantics, or sensor integration.
- Video storage, supported agent/CLI clients, automated cloud cleanup, or a
  rollback framework.

## GitHub tracking

- [Milestone 2 — Board MAVLink WebRTC control](https://github.com/mparkachov/txing/milestone/2)
- [#130 — Promote MAVLink to a shared board contract and define TBot capability](https://github.com/mparkachov/txing/issues/130)
- [#131 — Provision TBot MAVLink signaling and lifecycle state](https://github.com/mparkachov/txing/issues/131)
- [#132 — Run TBot MAVLink control through the board runtime](https://github.com/mparkachov/txing/issues/132)
- [#133 — Control TBot over MAVLink from Office](https://github.com/mparkachov/txing/issues/133)
- [#134 — Ship the forward-only TBot MAVLink cutover](https://github.com/mparkachov/txing/issues/134)
- [#119 — Validate TBot MAVLink WebRTC control on physical hardware](https://github.com/mparkachov/txing/issues/119)
