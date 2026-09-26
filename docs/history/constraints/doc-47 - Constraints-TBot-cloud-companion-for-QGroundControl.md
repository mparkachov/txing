---
id: doc-47
title: 'Constraints: TBot cloud companion for QGroundControl'
type: guide
created_date: '2026-09-26 00:00'
updated_date: '2026-09-26 00:00'
tags:
  - tbot
  - cloud
  - mavlink
  - qgroundcontrol
  - constraints
---

# TBot cloud companion constraints

These rules govern the TBot cloud companion described in
`doc-47 - TBot-cloud-companion-for-QGroundControl-architecture.md`.

- Scope is TBot only. REDCON 2 and 1 are active; REDCON 3, REDCON 4, and
  `DDEATH` require no companion task and no published usable endpoint.
- The projected `sparkplug` named shadow is lifecycle evidence. The companion
  shadow is operational status and must not affect REDCON derivation. Keep rig,
  witness, board, and companion shadow ownership separate.
- Reuse the existing MAVLink WebRTC channel, `txing.mavlink.v1` data-channel
  label, one-frame-per-message representation, and JSON lease protocol. Do not
  change the board's five-second lease or enable implicit takeover.
- A cloud task is an observer until its selected UDP sender sends a valid
  MAVLink arm command. Do not forward pre-arm uplink or acquire a lease on task
  start. Forward valid frames byte-for-byte after activation. Release on
  disarm, five-second sender inactivity, link loss, or shutdown.
- Only one UDP sender is selected per task at a time. The endpoint is public,
  dual-stack, and unauthenticated on UDP 14550. IPv4 is required for current
  QGroundControl; IPv6 remains available. Do not represent address obscurity as
  security.
- Video receive begins at REDCON 1 and stops at REDCON 2. Video failure cannot
  interrupt MAVLink or terminate a task that otherwise remains healthy.
- Do not expose a stale address as ready. Fence task status updates by task
  identity, clear endpoint fields on stop or failure, and reconcile at least
  once per minute in addition to lifecycle events.
- Use versioned immutable ECR image digests and release-built Go Lambda
  artifacts. Deploy infrastructure forward through CloudFormation. Preserve
  manual AWS rollout and operator-run physical acceptance; do not add AWS
  mutation to automated agent validation.
