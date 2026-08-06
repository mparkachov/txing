---
id: doc-35
title: 'Constraints: Cyberbrick ArduPilot board runtime'
type: guide
created_date: '2026-08-06 11:06'
updated_date: '2026-08-06 11:06'
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

## Source lifecycle and ownership

- The shared ArduPilot checkout lives only under `devices/common/ardupilot/` and
  is managed by explicit install/update tooling. It follows upstream `master`;
  it is not a vendored snapshot in the txing repository.
- Install/update may clone or fast-forward only a clean managed checkout and
  must initialize required submodules and report the resolved upstream SHA.
  Build, check, package, and clean operations must not fetch or change the
  selected upstream revision.
- A dirty, divergent, detached, or otherwise unmanaged checkout is a hard
  failure. Tooling must not discard a developer's source changes to recover.
- Cyberbrick target input and downstream patches live under
  `devices/cyberbrick/ardupilot/`. Shared code must not embed the Cyberbrick
  hardware definition or silently select Cyberbrick policy.
- The maintained ordered patch extracts only the generic Linux subtype, sysfs
  RC-output selection, and no-IMU backend support required from upstream PR
  #33691. Patch drift against the selected `master` is a hard failure requiring
  a reviewed refresh.
- Patches are temporary build inputs. Every operation that applies them must
  reverse them on success, command failure, and interruption, and the managed
  checkout must be clean when control returns.

## Build and artifact rules

- ArduRover is the only vehicle target. It is configured for Linux with the
  Cyberbrick extra hardware definition, sysfs PWM chip 0 channels 0-1, no
  onboard IMU or barometer, the native toolchain, and static linkage.
- Alpine 3.24.1 arm64 is the only build and execution environment. Do not add a
  Debian container, Debian package source, Debian smoke test, or Debian runtime
  promise for this component.
- The release executable is a stripped static aarch64 ELF with no `INTERP`
  program header. `--help` must execute successfully in the pinned Alpine
  environment.
- `txing-cyberbrick-ardupilot-linux-aarch64.tar.gz` contains one root entry,
  named `txing-cyberbrick-ardupilot`, and no source or runtime configuration.
- `txing-cyberbrick-ardupilot-source.tar.gz` contains the exact patched source
  for the released binary, all initialized submodules needed to rebuild it, the
  GPL license, machine-readable provenance, and build instructions.
- Binary and source release inputs must agree on upstream SHA, ordered patch
  checksums, txing commit, and Cyberbrick release version. Release notes expose
  the same provenance. The first publication belongs to the next Cyberbrick
  minor version in the existing `cyberbrick-v*` stream.
- Root-owned mise uses a separate configuration for the ArduPilot asset.
  Installation and upgrades remain explicit operator actions during a writable
  root maintenance window; service starts remain offline.

## Runtime and safety rules

- The OpenRC service name and executable name are both
  `txing-cyberbrick-ardupilot`. The service uses `supervise-daemon` with bounded
  respawns and is enabled in the default runlevel only after PWM ownership has
  been switched safely.
- SERIAL0 listens at `udpin:0.0.0.0:14550`. This unauthenticated, all-interface
  endpoint is allowed only on a trusted LAN. No claim of internet-safe exposure
  is permitted.
- Storage and terrain live under
  `/var/tmp/txing-cyberbrick-ardupilot/`; logs live under
  `/var/log/txing-cyberbrick-ardupilot/`. They are tmpfs-backed, ephemeral, and
  recreated empty after reboot. No persistent fallback may be introduced in
  this milestone.
- ArduPilot exclusively owns PWM chip 0 channels 0 and 1. The Cyberbrick
  hardware worker must be stopped and removed from the default runlevel before
  ArduPilot is enabled. Reciprocal start guards must reject concurrent service
  operation.
- The daemon and KVS master remain enabled. Their gRPC, MQTT, Thing Shadow, MCP,
  video, and REDCON contracts do not change; absence of the hardware worker is
  represented through existing motion-unavailable behavior.
- Hardware acceptance is service-only on a Raspberry Pi Zero 2 W with motor
  power physically isolated. Agents do not energize motors, arm ArduPilot, or
  flash/program firmware.

## Explicit non-goals

- No txing protocol integration or control path.
- No direction-GPIO or motor-actuation validation.
- No crash-time actuator failsafe claim.
- No durable parameters, terrain, or logs.
- No firewall policy or MAVLink signing.
- No ArduCopter or other vehicle build.
- No Debian support or compatibility work.

## GitHub tracking

- [Milestone 1 — Cyberbrick ArduPilot board runtime](https://github.com/mparkachov/txing/milestone/1)
- [#110 — Manage upstream ArduPilot source and Cyberbrick patch transactions](https://github.com/mparkachov/txing/issues/110)
- [#111 — Produce a validated Cyberbrick ArduRover Alpine build](https://github.com/mparkachov/txing/issues/111)
- [#112 — Publish provenance-complete Cyberbrick ArduPilot release assets](https://github.com/mparkachov/txing/issues/112)
- [#113 — Run Cyberbrick ArduPilot safely under OpenRC](https://github.com/mparkachov/txing/issues/113)
