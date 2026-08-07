---
id: doc-34
title: Cyberbrick ArduPilot board runtime architecture
type: specification
created_date: '2026-08-06 11:06'
updated_date: '2026-08-07 21:05'
tags:
  - ardupilot
  - cyberbrick
  - board
  - alpine
  - openrc
---

# Cyberbrick ArduPilot board runtime architecture

## Outcome and scope

Cyberbrick gains ArduRover as a fourth board component. A Cyberbrick release
ships a static aarch64 executable named `txing-cyberbrick-ardupilot`, installs
it with the existing root-owned mise configuration, and runs it as the
supervised OpenRC service `txing-cyberbrick-ardupilot` on the Alpine companion
board.

This phase proves that ArduPilot can be sourced, patched, built, released,
installed, and kept running on the board. It does not connect ArduPilot to the
txing daemon, MQTT, Thing Shadows, MCP, REDCON, or the existing hardware-worker
protocol. The daemon and KVS master remain enabled; the daemon's existing
degraded behavior reports motion hardware unavailable while its hardware worker
is disabled.

## Direct source and patch workflow

`devices/common/board/ardupilot/` is an ignored, disposable clone of live
upstream ArduPilot `master`. The checkout command runs a recursive,
single-branch clone. It does not update, inspect, repair, replace, or recover an
existing checkout. A clone failure is returned directly; starting again means
deleting the ignored checkout manually and cloning again.

Cyberbrick owns its tracked `hwdef.dat` and ordered downstream patches under
`devices/cyberbrick/ardupilot/`. The patches retain only the generic Linux
subtype, sysfs RC-output selection, and no-IMU support derived from upstream
[PR #33691](https://github.com/ArduPilot/ardupilot/pull/33691). A single
standard `git apply` command applies the ordered patch files and leaves them in
the checkout. Patch failure stops the operation; there is no preflight index,
transaction wrapper, automatic reversal, fallback, or recovery path.

The public Cyberbrick Just interface is deliberately small:

- `ardupilot::checkout` clones upstream `master` and its submodules.
- `ardupilot::patch` applies the ordered Cyberbrick patches.
- `ardupilot::build` builds the already-patched checkout.

## Target and build

The target uses ArduPilot's Linux board with a Cyberbrick subtype, native Linux
toolchain, sysfs PWM chip 0 channels 0-1, and no onboard IMU or barometer. Only
ArduRover is built. The build runs ArduPilot's stock Alpine prerequisite script
and then `waf configure --board linux --extra-hwdef ... --static` followed by
`waf rover` in the repository's pinned Alpine 3.24.1 arm64 environment. There
is no Debian build or compatibility lane.

The build relies on command exit status. It adds no custom checkout, patch,
build, or provenance test suite. Release packaging retains only small assertions
that the expected executable exists, is a static aarch64 ELF without a program
interpreter, runs `--help` in Alpine, and is placed in the intended archive
shape.

## Release and corresponding source

The existing `cyberbrick-v*` release stream gains two assets:

- `txing-cyberbrick-ardupilot-linux-aarch64.tar.gz` contains the single
  root-level executable `txing-cyberbrick-ardupilot` for mise.
- `txing-cyberbrick-ardupilot-source.tar.gz` contains the same job's patched
  ArduPilot source, initialized submodules, upstream license, and build
  instructions.

The release job performs a fresh clone, applies the patches, packages the
corresponding source, builds and strips ArduRover, records the upstream SHA, and
publishes both archives with the other Cyberbrick assets. There is no patch
checksum manifest or cross-artifact provenance reconciliation framework. The
first release is Cyberbrick `0.16.0` in the existing immutable release stream.

ArduPilot is the fourth tool in the existing root-owned Cyberbrick mise
configuration. Installation and upgrades remain explicit operator actions in a
writable-root maintenance window; service startup stays offline.

## OpenRC runtime and PWM ownership

`txing-cyberbrick-ardupilot` runs under the existing bounded
`supervise-daemon` convention and is enabled in the default runlevel. ArduRover
listens on SERIAL0 at `udpin:0.0.0.0:14550`. Storage and terrain live under
`/var/tmp/txing-cyberbrick-ardupilot/`, and logs live under
`/var/log/txing-cyberbrick-ardupilot/`. These paths are tmpfs-backed and are
recreated empty after a read-only-root reboot.

ArduPilot exclusively owns PWM chip 0 channels 0 and 1 while it runs. The
operator stops `txing-cyberbrick-hardware-worker` and removes it from the
default runlevel before enabling ArduPilot. Switching back reverses those
manual OpenRC steps. No reciprocal start guards or automatic service fallback
are added. The daemon and KVS master continue running without contract changes.

MAVLink is unauthenticated and bound on all interfaces. This milestone permits
that exposure only on a trusted LAN; firewalling and MAVLink signing remain
future security work.

## Validation and rollout

There are no ArduPilot-specific automated lifecycle, patch, build, provenance,
or workflow tests. The release job retains the minimal executable, static ELF,
`--help`, license, and archive-shape assertions described above.

Final acceptance is manual on a Raspberry Pi Zero 2 W with motor power
physically isolated. The operator installs the release through mise, disables
the hardware worker, enables ArduPilot, confirms stable OpenRC supervision and
UDP port 14550, and reboots with the root filesystem read-only. After reboot,
the ArduPilot service must start automatically, its tmpfs state must be empty,
and the daemon and KVS master must remain healthy while motion is unavailable.

No motor actuation, arming, direction-GPIO integration, crash-time actuator
failsafe, durable parameters/terrain/logs, or txing protocol integration is
part of this acceptance.

## GitHub tracking

- [Milestone 1 — Cyberbrick ArduPilot board runtime](https://github.com/mparkachov/txing/milestone/1)
- [#110 — Checkout and patch ArduPilot master](https://github.com/mparkachov/txing/issues/110)
- [#111 — Build Cyberbrick ArduRover for Alpine](https://github.com/mparkachov/txing/issues/111)
- [#112 — Publish Cyberbrick ArduPilot release assets](https://github.com/mparkachov/txing/issues/112)
- [#113 — Install and run Cyberbrick ArduPilot on the board](https://github.com/mparkachov/txing/issues/113)
