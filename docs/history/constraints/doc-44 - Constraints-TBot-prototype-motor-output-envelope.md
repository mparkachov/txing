---
id: doc-44
title: 'Constraints: TBot prototype motor output envelope'
type: guide
created_date: '2026-09-06 00:00'
tags:
  - tbot
  - ardupilot
  - motors
  - pwm
  - constraints
---

# Constraints: TBot prototype motor output envelope

These rules govern the temporary TBot battery-current workaround described in
`doc-43 - TBot-prototype-motor-output-envelope-architecture.md`. They supersede
the TBot full-duty assumptions in `doc-38`, `doc-39`, `doc-40`, and `doc-41`
only while the current prototype power hardware requires the workaround.

## Configuration rules

- Use `TXING_MOTOR_RAW_MAX_SPEED`, `TXING_MOTOR_CMD_RAW_MIN_SPEED`, and
  `TXING_MOTOR_CMD_RAW_MAX_SPEED` from the existing TBot `daemon.env`; do not
  introduce cloud, shadow, custom MAVLink, or custom ArduPilot configuration.
- Require all three values at TBot ArduPilot startup. Fail with both tracks
  neutral when values are missing, non-numeric, or fail the same ordering and
  range rules used by the Unit hardware worker.
- Apply changes only after an explicit ArduPilot service restart. Do not add a
  watcher, reload path, or automatic configuration writer.
- Do not consume PWM frequency, GPIO/channel mapping, inversion, kinematic,
  watchdog, or left/right track-power values from `daemon.env` in ArduPilot.

## Motor rules

- Apply the envelope independently to each TBot brushed PWM channel after
  ArduRover mixing so pivots and differential turns cannot exceed it.
- Preserve true neutral at zero. Map every nonzero magnitude into the inclusive
  command-minimum/command-maximum interval and cap maximum output at command
  maximum.
- Preserve standard ArduRover brushed-with-relay functions, ESC endpoints,
  direction relays, arming behavior, failsafes, and `MOT_PWM_FREQ` behavior.
- Keep the Unit hardware worker unchanged and do not copy its per-track trim to
  TBot.
- Treat the envelope as current-demand mitigation only. Do not claim hardware
  over-current protection or hard-crash neutralization.

## Compatibility rules

- Preserve the full `txing.mavlink.v1` contract: one complete MAVLink 2 frame
  per binary message, byte-for-byte forwarding, and no message allowlist,
  translation, or rewrite.
- Do not change shared MAVLink protobufs, schemas, Office behavior, cloud
  resources, device manifests, or REDCON semantics.
- Keep the workaround inside the TBot host sysfs PWM backend. A serial-connected
  physical flight controller must remain unaffected.

## Validation and rollout rules

- Prove automated boundaries for neutral, nonzero floor, midpoint, cap, and
  above-cap inputs on both tracks, including alternate valid values and invalid
  startup configurations.
- Run the patched TBot ArduPilot build/tests, existing Unit hardware-worker
  tests, full-frame MAVLink compatibility tests, and board configuration/OpenRC
  checks.
- Bump the TBot component version before publishing changed ArduPilot and source
  artifacts. Keep release assets immutable and matching.
- Install and restart manually with motor power isolated. Perform powered tests
  only with the chassis lifted and secured and an immediate physical power cut
  available; agents do not energize or drive hardware.

## Removal rule

Remove the TBot-only envelope and its service dependency on motor-limit
environment values when the battery/power design is validated for the intended
full motor range. Removal is a separate approved change; do not silently turn
this temporary workaround into a permanent product contract.

## GitHub tracking

- [Milestone 7 — TBot prototype motor output envelope](https://github.com/mparkachov/txing/milestone/7)
- [#138 — Bound TBot brushed PWM output to the configured motor envelope](https://github.com/mparkachov/txing/issues/138)
- [#139 — Load the TBot prototype motor envelope from daemon.env](https://github.com/mparkachov/txing/issues/139)
- [#140 — Ship the bounded TBot ArduPilot runtime](https://github.com/mparkachov/txing/issues/140)
- [#141 — Validate the TBot motor envelope on lifted hardware](https://github.com/mparkachov/txing/issues/141)
