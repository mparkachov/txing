---
id: doc-34
title: Cyberbrick ArduPilot board runtime architecture
type: specification
created_date: '2026-08-06 11:06'
updated_date: '2026-08-06 11:06'
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
it independently through root-owned mise, and runs it as the supervised OpenRC
service `txing-cyberbrick-ardupilot` on the Alpine companion board.

This phase proves that ArduPilot can be sourced, patched, built, released,
installed, and kept running on the board. It does not connect ArduPilot to the
txing daemon, MQTT, Thing Shadows, MCP, REDCON, or the existing hardware-worker
protocol. The daemon and KVS master remain enabled; the daemon's existing
degraded behavior reports motion hardware unavailable while its hardware worker
is disabled.

## Source and device ownership

The ArduPilot repository is a managed shared checkout under
`devices/common/ardupilot/`. Shared tooling installs the checkout or
fast-forwards a clean checkout to upstream `master`, initializes every submodule
needed by the build, and records the resolved upstream commit. An install or
update action may contact upstream; a build consumes the current checkout and
must never fetch or advance it implicitly.

Cyberbrick owns all device-specific input under
`devices/cyberbrick/ardupilot/`: its external `hwdef.dat`, the ordered downstream
patch series, and device build/check/clean entry points. The maintained patch is
a refreshed extraction of the generic changes from upstream
[PR #33691](https://github.com/ArduPilot/ardupilot/pull/33691): the Linux board
subtype, sysfs RC-output selection, and operation without an IMU backend. The
Cyberbrick hardware definition is not copied into the upstream checkout and is
passed to ArduPilot through `--extra-hwdef`.

Patch application is transactional. A build starts only from a clean managed
checkout, validates each ordered patch for drift, applies it temporarily, and
reverses it on both success and failure. A dirty checkout or a patch that no
longer applies to current `master` is an explicit maintenance failure, not a
reason to mutate or silently replace local source.

## Target and build contract

The target uses ArduPilot's Linux board with a Cyberbrick subtype, native Linux
toolchain, sysfs PWM chip 0 and channels 0-1, and no onboard IMU or barometer.
Only ArduRover is configured and built. The build uses `--board linux`, the
external Cyberbrick hardware definition, and `--static` in the repository's
pinned Alpine 3.24.1 arm64 environment. There is no Debian build or
compatibility lane.

The build is accepted only when its stripped output is an aarch64 ELF with no
program interpreter, runs `--help` in Alpine, and leaves the managed upstream
checkout clean. Generated hardware-definition evidence must identify the
Cyberbrick subtype and the intended two-channel sysfs PWM mapping.

Common and Cyberbrick Just commands mirror the existing MCU lifecycle: common
source installation/update plus device build, check, and clean operations. The
source lifecycle and patch transaction are covered by automated tests,
including reversal after failed builds and deterministic provenance output.

## Release and GPL provenance

The existing `cyberbrick-v*` release stream gains two assets:

- `txing-cyberbrick-ardupilot-linux-aarch64.tar.gz` contains exactly the single
  executable `txing-cyberbrick-ardupilot` at the archive root for mise.
- `txing-cyberbrick-ardupilot-source.tar.gz` contains the exact patched source
  corresponding to that binary, initialized submodules, the GPL license,
  provenance, and build instructions.

Release metadata and notes identify the resolved upstream SHA, ordered patch
checksums, txing commit, and Cyberbrick release version. Capturing both the
resolved SHA and corresponding-source archive in an immutable release closes
the reproducibility gap created by intentionally following live upstream
`master`. The feature advances the Cyberbrick component stream to its next
minor release.

ArduPilot uses a separate root-owned mise configuration so it can be installed
and upgraded with the other Cyberbrick assets without coupling service startup
to mise or GitHub availability.

## OpenRC runtime and hardware ownership

`txing-cyberbrick-ardupilot` runs under `supervise-daemon` with bounded
respawns and is enabled in the default runlevel. It starts ArduRover with a
MAVLink SERIAL0 listener at `udpin:0.0.0.0:14550`. Parameter storage and terrain
are under `/var/tmp/txing-cyberbrick-ardupilot/`; logs are under
`/var/log/txing-cyberbrick-ardupilot/`. These locations are tmpfs-backed on the
read-only-root board and are deliberately recreated empty after reboot.

ArduPilot exclusively owns `/sys/class/pwm/pwmchip0/pwm0` and `pwm1`. Before
ArduPilot is enabled, the operator stops
`txing-cyberbrick-hardware-worker` and removes it from the default runlevel.
Reciprocal OpenRC start guards reject either service while the other is active,
preventing concurrent control even after an operator mistake. The daemon and
KVS master continue running without any contract changes.

MAVLink is unauthenticated and bound on all interfaces. This milestone permits
that exposure only on a trusted LAN; firewalling and MAVLink signing remain
future security work.

## Validation and rollout

Automated validation covers checkout cleanliness and fast-forward behavior,
ordered patch application and reversal, patch drift, provenance, generated
target settings, Alpine static-linkage and execution, archive contents, and
release inputs.

The final service acceptance is operator-run on a Raspberry Pi Zero 2 W with
motor power physically isolated. The operator switches ownership from the
hardware worker to ArduPilot, verifies reciprocal guards, confirms stable
supervision without respawn churn, observes UDP port 14550 on all interfaces,
and reboots with the root filesystem read-only. After reboot the ArduPilot
service must start automatically, its tmpfs state must be empty, and the daemon
and KVS master must remain healthy while motion is unavailable.

No motor actuation, arming, direction-GPIO integration, crash-time actuator
failsafe, durable parameters/terrain/logs, or txing protocol integration is
part of this acceptance.

## GitHub tracking

- [Milestone 1 — Cyberbrick ArduPilot board runtime](https://github.com/mparkachov/txing/milestone/1)
- [#110 — Manage upstream ArduPilot source and Cyberbrick patch transactions](https://github.com/mparkachov/txing/issues/110)
- [#111 — Produce a validated Cyberbrick ArduRover Alpine build](https://github.com/mparkachov/txing/issues/111)
- [#112 — Publish provenance-complete Cyberbrick ArduPilot release assets](https://github.com/mparkachov/txing/issues/112)
- [#113 — Run Cyberbrick ArduPilot safely under OpenRC](https://github.com/mparkachov/txing/issues/113)
