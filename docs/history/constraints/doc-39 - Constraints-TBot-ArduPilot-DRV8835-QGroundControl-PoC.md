---
id: doc-39
title: 'Constraints: TBot ArduPilot DRV8835 QGroundControl PoC'
type: guide
created_date: '2026-08-26 00:00'
updated_date: '2026-08-26 00:00'
tags:
  - ardupilot
  - tbot
  - drv8835
  - qgroundcontrol
  - constraints
---

# Constraints: TBot ArduPilot DRV8835 QGroundControl PoC

These rules constrain the TBot ArduPilot proof of concept described in
`doc-38 - TBot-ArduPilot-DRV8835-QGroundControl-PoC-architecture.md`.

## Source and ownership rules

- Use the ignored disposable checkout at `devices/common/board/ardupilot/` and
  live upstream `master`, including all submodules, as the sole source
  baseline. Do not depend on a fork or an unmerged upstream pull request.
- Keep every TBot hardware definition, default parameter, OpenRC service, and
  ordered downstream patch under `devices/tbot/ardupilot/`.
- Do not read, move, or modify Cyberbrick's tracked ArduPilot patches for a TBot
  build.
- Apply only one device patch stack to a clean shared checkout. Recovery from
  existing or partially patched state is manual checkout disposal and reclone;
  do not add repair, reversal, fallback, or combined-patch behavior.
- Build only ArduRover with the native Linux toolchain in Alpine 3.24.1 arm64.
  Do not add Debian, emulated, or non-arm64 release lanes.

## Motor rules

- ArduPilot exclusively owns `pwmchip0` channels `0` and `1` and physical BCM
  GPIO lines `5` and `6` while it runs.
- Use upstream ArduRover `MOT_PWM_TYPE=3` (`BrushedWithRelay`),
  `SERVO1_FUNCTION=73`, and `SERVO2_FUNCTION=74` for motor mixing.
- Use upstream relay functions for direction: `RELAY1_FUNCTION=5` on
  `RELAY1_PIN=5` and `RELAY2_FUNCTION=6` on `RELAY2_PIN=6`. Do not add
  `SERVOx_DIR_GPIO` parameters or TBot-specific direction handling.
- Do not override `MOT_PWM_FREQ` in TBot defaults. Retain upstream's 16 kHz
  default and its MAVLink-configurable `1..20 kHz` range and reboot
  requirement; do not hard-code 20 kHz or preserve the sysfs initialization
  frequency of 50 Hz after Rover selects brushed mode.
- Make Linux sysfs outputs honor `MODE_PWM_BRUSHED`: configured ESC minimum is
  0% duty, configured ESC maximum is 100% duty, and intermediate magnitudes
  are linear. Do not interpret `1500 us` as neutral in this mode.
- Use upstream's zero minimum and full maximum throttle defaults. Do not copy
  the hardware worker's `250/480` power cap or minimum nonzero command.
- Use standard upstream relay direction behavior. During powered acceptance,
  return the command to neutral before selecting the opposite direction; do
  not claim a TBot-specific zero-before-direction-change guarantee.
- Initialization, disable, `force_safety_on`, and graceful exit must attempt to
  neutralize both tracks.
- On hardware access failure, attempt neutralization and fail the process; do
  not silently continue with partial actuator availability.
- Do not claim neutralization after `SIGKILL`, kernel failure, or an unhandled
  process crash. A hardware watchdog is outside this milestone.

## Runtime and network rules

- Install `txing-tbot-ardupilot` as an optional OpenRC service; do not add it to
  the default runlevel.
- Leave `txing-tbot-hardware-worker` in the default runlevel. A reboot must
  restore the normal worker-owned runtime.
- Add no automatic service switching, reciprocal start guard, fallback, or
  recovery. The operator is responsible for never running both motor owners.
- Keep the daemon and KVS master running without changing their contracts or
  configuration. Existing worker-unavailable behavior is the only integration.
- Listen for unsigned MAVLink 2 on `udpin:0.0.0.0:14550`; do not add an
  operator-specific address to board configuration.
- Permit the endpoint only on a trusted isolated LAN. Do not add firewall,
  authentication, MAVLink signing, WebRTC, cloud, or Office transport work.
- Keep storage, terrain, and logs ephemeral on the existing tmpfs-backed board
  paths. Do not add persistent parameter or log storage.

## Release rules

- Publish the binary/defaults and corresponding patched source in the same
  immutable `tbot-v0.18.0` release job.
- Name the assets `txing-tbot-ardupilot-linux-aarch64.tar.gz` and
  `txing-tbot-ardupilot-source.tar.gz`.
- Record the upstream SHA and prove that the source asset contains initialized
  submodules, the upstream license, and build instructions.
- Validate that the stripped executable is static aarch64 without a program
  interpreter and runs `--help` in pinned Alpine.
- Do not publish a binary-only TBot ArduPilot release or install a source
  checkout on the board.

## Acceptance rules

- Perform initial service and UDP validation with motor power physically
  isolated.
- Perform powered motion acceptance only with the chassis lifted and secured
  and an immediate physical power cut available.
- Use ordinary QGroundControl arming and joystick control; forced arming is not
  acceptance.
- Verify telemetry, parameter download, the expected standard motor and relay
  assignments, and visibility of `MOT_PWM_FREQ` through MAVLink. Verify
  forward/reverse through neutral for each track, differential turns, full
  duty, neutral on joystick release and disarm, one-second GCS-loss Hold, and
  neutral on graceful service stop.
- Restore and verify the hardware worker, then reboot and verify that ArduPilot
  remains stopped.
- Do not change motor, relay, or failsafe parameters during powered acceptance.
  A `MOT_PWM_FREQ` experiment is optional and must be performed with motor
  power isolated before restarting ArduPilot.

## Explicit non-goals

- No TBot manifest, schema, shadow, MQTT, gRPC, MCP, daemon, KVS, Office, rig,
  or AWS contract changes.
- No floor driving, autonomous navigation, mission execution, GPS, IMU,
  barometer, or sensor fusion.
- No automatic service ownership, crash-time hardware watchdog, durable
  ArduPilot data, signed MAVLink, or untrusted-network exposure.
- No firmware flashing or programming.
