---
id: doc-35
title: 'Constraints: Cyberbrick ArduPilot board runtime'
type: guide
created_date: '2026-08-06 11:06'
updated_date: '2026-08-07 21:05'
tags:
  - ardupilot
  - cyberbrick
  - board
  - alpine
  - openrc
  - constraints
---

# Constraints: Cyberbrick ArduPilot board runtime

These rules extend the Alpine and static-linkage requirements in
`doc-29 - Constraints-cyberbrick-Alpine-board.md` and
`doc-32 - Constraints-board-musl-static-builds.md` for the Cyberbrick ArduPilot
component.

## Source and patch rules

- The disposable upstream checkout lives at
  `devices/common/board/ardupilot/`, follows live upstream `master`, includes
  its submodules, and is ignored by the txing repository.
- Checkout uses a direct recursive, single-branch clone. It has no update,
  validation, repair, replacement, or fallback behavior. An existing checkout
  or any Git failure is returned directly.
- Cyberbrick's tracked external hardware definition and ordered patches live
  under `devices/cyberbrick/ardupilot/`.
- A standard `git apply` invocation applies the ordered patches and leaves them
  applied. Patch drift or partial local state is handled by manually discarding
  the disposable checkout and starting again; no transactional patch tooling
  or automatic reversal is allowed.
- The patches contain only the generic Linux subtype, sysfs RC-output
  selection, and no-IMU support required from upstream PR #33691.

## Build and artifact rules

- ArduRover is the only vehicle target. It is configured for Linux with the
  Cyberbrick extra hardware definition, sysfs PWM chip 0 channels 0-1, no
  onboard IMU or barometer, the native toolchain, and static linkage.
- Alpine 3.24.1 arm64 is the only build and execution environment. Use
  ArduPilot's stock Alpine prerequisite script. Do not add a Debian build,
  package, smoke, or compatibility path for this component.
- The release executable is named `txing-cyberbrick-ardupilot`, is stripped,
  and is a static aarch64 ELF without a program interpreter.
- `txing-cyberbrick-ardupilot-linux-aarch64.tar.gz` contains only the
  root-level executable of the same name.
- `txing-cyberbrick-ardupilot-source.tar.gz` is produced from the same patched
  checkout as the binary and contains its initialized submodules, upstream
  license, and build instructions.
- The release records the resolved upstream SHA but adds no patch-checksum
  manifest, provenance reconciliation framework, fallback, or ArduPilot test
  suite.
- The first publication is Cyberbrick `0.16.0` in the existing immutable
  `cyberbrick-v*` stream.
- ArduPilot is the fourth tool in the existing root-owned Cyberbrick mise
  configuration. Installation and upgrades remain explicit operator actions;
  service startup remains offline.

## Runtime and safety rules

- The OpenRC service and executable are both named
  `txing-cyberbrick-ardupilot`. The service uses the existing bounded
  `supervise-daemon` convention and is enabled only after PWM ownership has
  been switched manually.
- SERIAL0 listens at `udpin:0.0.0.0:14550`. This unauthenticated,
  all-interface endpoint is allowed only on a trusted LAN.
- Storage and terrain live under
  `/var/tmp/txing-cyberbrick-ardupilot/`; logs live under
  `/var/log/txing-cyberbrick-ardupilot/`. They are tmpfs-backed, ephemeral, and
  recreated empty after reboot.
- ArduPilot exclusively owns PWM chip 0 channels 0 and 1 while running. The
  operator must stop the Cyberbrick hardware worker and remove it from the
  default runlevel before enabling ArduPilot. Switching back is also manual.
- No reciprocal OpenRC guards, automatic switching, recovery, or runtime
  fallback are added. Operator error can start conflicting services, so the
  runbook must make the switching sequence explicit.
- The daemon and KVS master remain enabled. Their gRPC, MQTT, Thing Shadow,
  MCP, video, and REDCON contracts do not change; absence of the hardware
  worker uses existing motion-unavailable behavior.
- Hardware acceptance is service-only on a Raspberry Pi Zero 2 W with motor
  power physically isolated. Agents do not energize motors, arm ArduPilot, or
  flash/program firmware.

## Validation policy

- Do not add ArduPilot-specific unit, integration, checkout-state,
  patch-transaction, provenance, or workflow tests.
- Release validation is limited to executable existence, static aarch64 ELF
  linkage without an interpreter, Alpine `--help` execution, upstream license
  presence, and archive shape.
- Runtime acceptance is performed manually on the board after installation,
  OpenRC switching, and read-only-root reboot.

## Explicit non-goals

- No txing protocol integration or control path.
- No direction-GPIO or motor-actuation validation.
- No crash-time actuator failsafe claim.
- No durable parameters, terrain, or logs.
- No firewall policy or MAVLink signing.
- No ArduCopter or other vehicle build.
- No Debian support or compatibility work.
- No automated checkout maintenance, rollback, or cleanup framework.

## GitHub tracking

- [Milestone 1 — Cyberbrick ArduPilot board runtime](https://github.com/mparkachov/txing/milestone/1)
- [#110 — Checkout and patch ArduPilot master](https://github.com/mparkachov/txing/issues/110)
- [#111 — Build Cyberbrick ArduRover for Alpine](https://github.com/mparkachov/txing/issues/111)
- [#112 — Publish Cyberbrick ArduPilot release assets](https://github.com/mparkachov/txing/issues/112)
- [#113 — Install and run Cyberbrick ArduPilot on the board](https://github.com/mparkachov/txing/issues/113)
