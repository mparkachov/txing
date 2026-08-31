---
id: doc-41
title: 'Constraints: TBot MAVLink WebRTC control'
type: guide
created_date: '2026-08-31 22:44'
updated_date: '2026-08-31 22:44'
tags:
  - tbot
  - mavlink
  - webrtc
  - ardupilot
  - board
  - office
  - constraints
---

# Constraints: TBot MAVLink WebRTC control

These rules govern TBot's forward-only replacement of MCP and the hardware
worker with the existing MAVLink-over-WebRTC architecture. They supersede only
the optional/manual/direct-UDP TBot runtime rules in `doc-38` and `doc-39`.
The Cyberbrick rules in `doc-36` and `doc-37` remain active and unchanged.

## Capability and compatibility rules

- TBot must declare `mavlink` and must not declare `mcp`; manifest validation
  continues to reject both capabilities together.
- TBot must not publish, translate, install, or retain an MCP compatibility
  path or a hardware-worker fallback.
- Unit, Cyberbrick, and every other device type keep their current manifests,
  contracts, releases, runtime ownership, and Office behavior.
- Shared MAVLink definitions may move to common board ownership, but existing
  protobuf packages, WebRTC labels, binary frames, JSON envelopes, descriptor
  values, and Cyberbrick behavior must not change.
- `capability.mavlink=true` requires a healthy local MAVLink service, a fresh
  flight-controller heartbeat, and a ready MAVLink KVS path. It does not
  require an Office peer.

## Runtime and motor-ownership rules

- ArduPilot is the exclusive TBot PWM and direction-GPIO owner. The TBot
  hardware worker must be absent from the release, installation, and default
  runlevel.
- `txing-tbot-mavlink` is independently supervised and owns
  `udp://127.0.0.1:14550` plus
  `/run/txing-tbot-mavlink/tbot-mavlink.sock`.
- ArduPilot must use `--serial1 udpin:127.0.0.1:14550`; it must not expose UDP
  14550 on all network interfaces.
- The daemon remains the sole authority for actor, session, epoch, takeover,
  lease, REDCON, and cloud state. KVS must use its MAVLink bridge API.
- The default OpenRC order is ArduPilot, MAVLink, daemon, then KVS master. All
  four services are boot-enabled.
- Preserve TBot's proven `MOT_PWM_TYPE=3`, left/right throttle outputs, relay
  reverse functions on BCM GPIO 5/6, and configurable upstream 16 kHz PWM
  default.
- Preserve the one-second GCS Hold failsafe and current no-sensor arming-check
  accommodation. Only ordinary non-forced arm/disarm is allowed.

## WebRTC and control rules

- `<thing>-board-video` remains video-only and `<thing>-mavlink` remains
  data-only, with separate peer connections, credentials, signaling, retries,
  and health.
- Camera initialization, capture, or video signaling failure must not stop or
  restart MAVLink control.
- The MAVLink channel remains ordered, reliable, and labeled
  `txing.mavlink.v1` with one complete unsigned MAVLink 2 common frame per
  binary message.
- Multiple peers may observe; only the current session and epoch may transmit.
  The lease remains five seconds and explicit takeover remains atomic.
- The uplink allowlist remains GCS heartbeat, `MANUAL_CONTROL`, ordinary
  arm/disarm, and Manual/Hold selection. Missions, parameters, reboot, forced
  arm/disarm, malformed frames, and wrong-source/target traffic remain denied.
- Office refreshes driving at 10 Hz. Stop, blur, page hide, active-channel
  close, and watchdog expiry must converge on neutral control.
- Active-channel close requests neutral and Hold immediately. Otherwise the
  independent watchdog must request neutral and Hold within 500 ms of the last
  accepted active control frame while leaving ArduPilot armed.

## Cloud and REDCON rules

- TBot publishes the existing MAVLink descriptor/status topics and named-shadow
  shape, and its catalog exposes `resources.mavlink.channelName`.
- Enlistment and service checks must create and validate `<thing>-mavlink` for
  TBot. A fresh TBot board credential role must authorize master access to both
  TBot signaling channels.
- Office remains viewer-only and receives no master authorization.
- REDCON3 means the board is powered but MAVLink is unavailable. REDCON2 means
  MAVLink is healthy but the full armed-plus-video posture is absent. REDCON1
  requires healthy MAVLink, healthy video, and `mavlinkArmed=true`.
- A REDCON1 request must never arm the rover. Disarming with healthy video must
  return TBot to REDCON2.
- Obsolete TBot MCP retained messages and named shadow are removed manually
  after cutover; do not add cleanup automation.

## Office rules

- TBot must use the existing MAVLink WebRTC session and control behavior rather
  than initializing the MCP drive path.
- At REDCON2, Office must support telemetry, control acquisition, takeover,
  arm/disarm, Manual/Hold, and drive without video.
- At REDCON1, Office adds the independent video peer while retaining TBot and
  Thread-specific presentation.
- Sharing Office components with Cyberbrick must not change Cyberbrick labels,
  behavior, or tests.

## Release and rollout rules

- Publish a TBot daemon, MAVLink service, ArduPilot/defaults, and corresponding
  patched-source assets; stop publishing the TBot hardware-worker asset.
- Use the next available immutable TBot and Office patch versions after
  checking current release tags.
- Provision catalog, KVS, and IAM state and generate a fresh certificate bundle
  before installing the board cutover.
- Deploy all TBot binaries, defaults, OpenRC files, and configuration in one
  writable-root maintenance window, then validate after a read-only reboot.
- Deploy Office only after board validation succeeds.
- Do not add dual-running, rollback, compatibility, automated cleanup, or
  automatic cloud-deployment mechanisms.
- Agents prepare commands and artifacts but do not mutate AWS resources, arm
  the rover, energize motors, or flash/program hardware.

## Validation policy

- Automated tests must cover shared protocol compatibility, TBot schemas and
  catalog state, KVS/IAM provisioning inputs, REDCON, local transport health,
  uplink filtering, leases/epochs/takeover, 500 ms safe state, independent
  video failure, Office behavior, release contents, and OpenRC policy.
- Unit MCP and Cyberbrick MAVLink behavior must pass unchanged compatibility
  tests.
- Physical acceptance is operator-run on a secured lifted TBot with motor power
  initially isolated and an immediate physical power cut available.
- Physical acceptance must cover loopback-only MAVLink, ordinary arming,
  forward/reverse/turn/neutral/disarm, video/control independence, concurrent
  observation, takeover, and neutral/Hold within 500 ms after active WebRTC
  loss.
- The earlier unperformed direct-GCS link-loss test is not an accepted
  limitation for this milestone. If the WebRTC-loss test is skipped or fails,
  final acceptance and the milestone remain open.

## Explicit non-goals

- Direct QGroundControl access or another LAN MAVLink endpoint.
- UART, signing, missions, parameter editing, autonomous control, or sensors.
- TBot MCP, hardware-worker fallback, or manual motor-owner switching.
- Changes to another device type's public behavior.
- Video storage, new motor electronics, stronger crash guarantees, supported
  agent/CLI clients, or automated cleanup and rollback.

## GitHub tracking

- [Milestone 2 — Board MAVLink WebRTC control](https://github.com/mparkachov/txing/milestone/2)
- [#130 — Promote MAVLink to a shared board contract and define TBot capability](https://github.com/mparkachov/txing/issues/130)
- [#131 — Provision TBot MAVLink signaling and lifecycle state](https://github.com/mparkachov/txing/issues/131)
- [#132 — Run TBot MAVLink control through the board runtime](https://github.com/mparkachov/txing/issues/132)
- [#133 — Control TBot over MAVLink from Office](https://github.com/mparkachov/txing/issues/133)
- [#134 — Ship the forward-only TBot MAVLink cutover](https://github.com/mparkachov/txing/issues/134)
- [#119 — Validate TBot MAVLink WebRTC control on physical hardware](https://github.com/mparkachov/txing/issues/119)
