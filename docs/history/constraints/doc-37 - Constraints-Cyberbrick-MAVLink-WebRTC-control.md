---
id: doc-37
title: 'Constraints: Cyberbrick MAVLink WebRTC control'
type: guide
created_date: '2026-08-11 09:55'
updated_date: '2026-08-11 09:55'
tags:
  - cyberbrick
  - mavlink
  - webrtc
  - ardupilot
  - office
  - constraints
---

# Constraints: Cyberbrick MAVLink WebRTC control

These rules govern the Cyberbrick MAVLink cutover. They supersede the
Cyberbrick-specific no-integration and trusted-LAN endpoint rules in `doc-34`
and `doc-35`, while preserving those documents as history for the completed
ArduPilot runtime milestone.

## Capability and compatibility rules

- Cyberbrick declares `mavlink` and does not declare `mcp`; validation must
  reject a manifest containing both.
- Unit keeps its current `mcp` capability, hardware worker, release artifacts,
  daemon initialization, shadows, topics, and Office behavior.
- Do not dual-publish, translate, or retain a compatibility path for
  Cyberbrick MCP control.
- `capability.mavlink=true` requires a healthy local MAVLink service, a fresh
  flight-controller heartbeat, and a ready MAVLink KVS master. An Office peer
  is not required.
- MAVLink arm state is separate flight-safety state. It is not a REDCON input
  or an additional capability.

## Runtime ownership and transport rules

- `txing-cyberbrick-mavlink` is an independently supervised OpenRC service and
  the only board component that owns the local flight-controller transport.
- Its Unix socket is
  `/run/txing-cyberbrick-mavlink/cyberbrick-mavlink.sock`, and its public local
  API is `txing.board.mavlink.v1.BoardMavlink` with `GetStatus`, `Exchange`, and
  `EnterSafeState`.
- Version 1 implements `TXING_MAVLINK_FC_ENDPOINT=udp://127.0.0.1:14550` behind
  a transport interface. A documented `serial:///dev/...?baud=...` syntax is
  reserved but must not be implemented in this milestone.
- ArduPilot listens on `udpin:127.0.0.1:14550`; it must not expose the MAVLink
  endpoint on all network interfaces.
- The daemon is the sole authority for session, actor, epoch, takeover, lease,
  REDCON, and cloud state. KVS must use the daemon's
  `txing.board.mavlink_bridge.v1.BoardMavlinkBridge` API rather than duplicating
  that authority.
- Cyberbrick must not initialize an MCP hardware client. Unit must not
  initialize the MAVLink bridge.

## KVS and WebRTC rules

- `<thing>-board-video` is a video-only KVS signaling channel and peer
  connection. `<thing>-mavlink` is a data-only channel and peer connection.
- One KVS master process owns both, but each has independent configuration,
  temporary credentials, signaling, peers, retries, and health state.
- Camera initialization and video signaling failures must not stop or restart
  the MAVLink control path.
- The data-only connection has exactly one ordered, reliable RTCDataChannel
  labeled `txing.mavlink.v1`; it does not require or negotiate a video
  transceiver.
- Each binary data-channel message contains exactly one complete unsigned
  MAVLink 2 common-dialect frame. Do not rewrite a valid frame.
- Text data-channel messages are JSON envelopes limited to
  `control.get_state`, `control.activate`, `control.renew_active`, and
  `control.release_active`. Responses use stable busy, stale-epoch, and invalid
  error codes.
- Generated common-dialect C/C++ and TypeScript bindings must be vendored from
  pinned definitions and tooling with provenance, licenses, golden vectors,
  and a reproducible regeneration check. Office must not add a runtime MAVLink
  dependency.
- Telemetry is broadcast to every observer. Per-peer queues are bounded, and a
  slow peer must not delay the flight-controller reader or another peer.

## Authorization and control rules

- Multiple peers may observe simultaneously. Exactly one session and epoch may
  send flight-controller uplink frames.
- The active-control lease is five seconds and requires explicit renewal.
  Explicit takeover atomically changes owner and epoch. Old-epoch frames fail
  immediately and takeover does not inject neutral or Hold.
- Uplink is limited to GCS `HEARTBEAT`, `MANUAL_CONTROL`, ordinary non-forced
  `MAV_CMD_COMPONENT_ARM_DISARM`, and Manual/Hold mode selection.
- Reject signed or malformed frames, wrong source or target, inactive or stale
  senders, missions, parameters, reboot, forced arm/disarm, and arbitrary
  commands.
- Only the active owner may arm or disarm. Both operations require
  `COMMAND_ACK` and matching heartbeat confirmation. Do not use force magic or
  blanket arming-check bypasses.
- Driving refreshes `MANUAL_CONTROL` at 10 Hz. ArduRover steering uses `.y`,
  throttle uses `.z`, and unused axes are invalid.
- Stop, blur, page hide, detected active-channel close, and watchdog expiry
  must converge on neutral control.

## Safety and REDCON rules

- A detected active-channel close requests neutral and Hold immediately.
- At most 500 ms after the last accepted active control packet, the independent
  watchdog requests neutral and Hold while leaving the rover armed.
- ArduPilot additionally applies a one-second GCS Hold failsafe.
- REDCON3 means the board is powered but MAVLink is unavailable.
- REDCON2 includes healthy MAVLink with unavailable video, regardless of arm
  state.
- REDCON1 requires healthy board, MAVLink, and video. Disarming with healthy
  video leaves Cyberbrick at REDCON1.
- A REDCON1 request may start the stack and video but must never arm.
- REDCON4 and shutdown attempt neutral, Hold, and disarm before halt through a
  bounded `EnterSafeState` call.
- Do not claim additional crash-time guarantees beyond existing ArduPilot,
  sysfs-PWM, and ESC behavior.

## Flight-controller and motor rules

- ArduPilot remains the exclusive PWM chip 0 channels 0-1 owner for the
  existing consumer-grade ESC setup.
- Do not add direction GPIO, 20 kHz H-bridge operation, or a hardware-worker
  motor fallback.
- The tracked ArduRover defaults are loaded on every tmpfs-backed boot and
  configure MAVLink 2, GCS system ID 255, Manual/Hold, left/right throttle
  functions, existing ESC pulse ranges, one-second GCS Hold failsafe, no RC
  receiver, and only minimum target-specific arming accommodations.
- The default OpenRC order is ArduPilot, MAVLink, daemon, then KVS master. The
  Cyberbrick hardware worker is disabled and removed from the runlevel.

## Cloud and publication rules

- Publish retained `txings/<thing>/mavlink/descriptor` without expiry and
  retained `txings/<thing>/mavlink/status` with the normal capability TTL.
- The `mavlink` named shadow contains link, target, armed/mode, peers,
  active-control, and error state. Do not add generic timestamps.
- Catalogs expose `resources.mavlink.channelName`; enlistment and validation
  create and check `<thing>-mavlink` and its credential policy permissions.
- Preserve the existing Office viewer authorization model for both Cyberbrick
  KVS channels.
- Obsolete Cyberbrick MCP retained messages and named shadow are removed
  manually after cutover. Do not add cleanup automation.

## Release and rollout rules

- Publish `txing-cyberbrick-mavlink-linux-aarch64.tar.gz` in the Cyberbrick
  release and stop publishing or installing the Cyberbrick hardware-worker
  artifact. Unit assets do not change.
- Package the tracked ArduPilot defaults alongside its executable and deploy
  all Cyberbrick binaries, defaults, OpenRC files, and configuration as one
  forward-only maintenance change while root is writable.
- Provision the KVS channel and IAM policy before board deployment. Deploy
  Office only after the read-only-root board reboot succeeds.
- Do not add an automated rollback, dual-publish period, or MCP compatibility
  shim.
- Agents prepare deployment instructions but do not provision AWS resources,
  energize motors, arm the rover, or flash/program hardware.

## Validation policy

- Automated tests must cover MAVLink vectors, CRC, framing, UDP reconnect,
  heartbeat freshness, allowlisting, lease/epoch/takeover, 500 ms Hold,
  multi-observer telemetry, slow-peer isolation, independent video/control
  failures, credential refresh, cloud projections, REDCON, and unchanged Unit
  MCP behavior.
- Office tests must cover data-only negotiation, observer-only use,
  active-owner arm/disarm acknowledgement, Rover `y/z` mapping, 10 Hz refresh,
  neutral on stop/blur/page hide, and takeover.
- Physical acceptance is operator-run with the Cyberbrick lifted and motor
  power initially isolated. It includes read-only-root reboot, service
  supervision, camera-failure independence, telemetry, arming to REDCON1,
  existing ESC/PWM motion directions, disarm, a second observer, takeover, and
  neutral/Hold within 500 ms after active connection loss.

## Explicit non-goals

- UART implementation.
- Supported agent or CLI clients.
- MAVLink signing.
- Missions, parameters, or autonomous control.
- Video storage.
- Cyberbrick MCP compatibility.
- New motor electronics.
- Stronger crash-time safety claims.

## GitHub tracking

- [Milestone 2 — Cyberbrick MAVLink WebRTC control](https://github.com/mparkachov/txing/milestone/2)
- [#114 — Define Cyberbrick MAVLink capability contracts](https://github.com/mparkachov/txing/issues/114)
- [#115 — Provision Cyberbrick MAVLink signaling and lifecycle state](https://github.com/mparkachov/txing/issues/115)
- [#116 — Run Cyberbrick MAVLink control through the board runtime](https://github.com/mparkachov/txing/issues/116)
- [#117 — Control Cyberbrick over MAVLink from Office](https://github.com/mparkachov/txing/issues/117)
- [#118 — Ship Cyberbrick ArduPilot and MAVLink services together](https://github.com/mparkachov/txing/issues/118)
- [#119 — Validate Cyberbrick MAVLink control on physical hardware](https://github.com/mparkachov/txing/issues/119)
