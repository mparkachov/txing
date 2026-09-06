---
id: doc-43
title: TBot prototype motor output envelope architecture
type: specification
created_date: '2026-09-06 00:00'
tags:
  - tbot
  - ardupilot
  - motors
  - pwm
  - battery
---

# TBot prototype motor output envelope architecture

## Outcome

TBot temporarily bounds the duty applied to each DRV8835 track because the
prototype battery cannot supply full motor current while also powering the
board. This is a software workaround for the current prototype, not a product
motor-control requirement or a device-definition property.

The existing `daemon.env` is the manual override surface. With the tracked
values `TXING_MOTOR_RAW_MAX_SPEED=480`,
`TXING_MOTOR_CMD_RAW_MIN_SPEED=100`, and
`TXING_MOTOR_CMD_RAW_MAX_SPEED=200`, neutral remains 0% duty and every
nonneutral TBot motor output remains between approximately 20.833% and 41.667%
duty. Changing those three values and restarting ArduPilot changes the
prototype envelope without rebuilding it.

Unit keeps its existing hardware-worker configuration and behavior. Cyberbrick
and future flight-controller-backed device types do not adopt this envelope.

## Configuration and runtime ownership

The boot-enabled `txing-tbot-ardupilot` OpenRC service reads the existing TBot
configuration file at `/root/.config/txing/tbot-daemon/daemon.env` and exports
only the three raw command-envelope values to its supervised ArduPilot process.
No cloud catalog, Thing Shadow, schema, protobuf, or new configuration key is
introduced.

The TBot Linux sysfs PWM adaptation loads and validates the three values before
enabling motor output. Configuration is valid only when raw maximum is
positive, command minimum is nonnegative, command maximum is positive, command
minimum is less than command maximum, and command maximum is no greater than
raw maximum. A missing or invalid value is a startup failure: both tracks stay
neutral and ArduPilot does not continue with an unrestricted fallback.

The configuration is intentionally startup-only. An operator edits
`daemon.env` and restarts `txing-tbot-ardupilot` while motor power is isolated.
There is no live reload, remote update, or persistent ArduPilot parameter.

## Output mapping

ArduRover retains standard `MOT_PWM_TYPE=3` brushed-with-relay mixing, servo
functions, relay direction, ESC endpoints, and PWM-frequency behavior. The
temporary envelope is applied below those semantics in the final Linux sysfs
output path, independently for each brushed channel and after skid-steer
mixing:

- an output at or below ArduPilot's ESC minimum writes zero duty;
- a nonneutral magnitude is linearly mapped from the configured raw command
  minimum through command maximum;
- a magnitude at or above ArduPilot's ESC maximum is capped at command maximum;
- raw output is converted to duty as `raw output / raw maximum * PWM period`,
  with nearest-integer rounding.

Applying the envelope at the final per-track output ensures a straight command,
differential turn, and full pivot cannot bypass the current cap. Direction
continues to be expressed through ArduPilot's standard relay behavior. The
Unit-only left/right track power percentages are not applied to TBot.

`MOT_PWM_FREQ` remains absent from TBot defaults, so the current upstream 16 kHz
default and normal restart-required MAVLink configurability remain unchanged.

## MAVLink and future hardware controllers

The board MAVLink path remains an ordered, reliable, byte-preserving tunnel of
complete MAVLink 2 frames. It does not filter, rewrite, or replace standard
MAVLink messages, and it adds no TBot motor-limit message or parameter.

The workaround belongs only to the host ArduPilot Linux sysfs adapter that
directly owns the prototype's PWM hardware. A later model using a physical
flight controller over a serial connection receives the same complete standard
MAVLink traffic and does not pass through this host PWM envelope.

## Validation and rollout

Focused ArduPilot tests cover zero, smallest nonzero, midpoint, maximum, and
above-maximum input on both brushed channels, plus alternate valid envelopes
and every invalid configuration class. With `480/100/200`, tests prove zero
stays zero and nonzero output remains in the `100/480..200/480` duty interval.
Existing full-frame MAVLink compatibility tests and Unit hardware-worker tests
must remain unchanged and pass.

Rollout requires the next immutable TBot release because the ArduPilot binary,
corresponding source archive, and OpenRC service change together. The operator
installs the matching TBot artifacts and service file, verifies the three
values in `daemon.env`, and restarts the TBot services in ownership order with
the chassis lifted and motor power initially isolated. Powered acceptance must
verify neutral, forward and reverse motion, differential turns, full pivots,
and the measured per-track duty ceiling with an immediate physical power cut
available.

## Risks and non-goals

The floor intentionally makes a smallest nonzero command jump to the configured
minimum duty, matching the prototype's existing raw command-envelope concept.
The cap mitigates expected current demand but is not over-current protection,
a hardware watchdog, or a guarantee after `SIGKILL`, kernel failure, or power
electronics failure.

Cloud-managed limits, live reconfiguration, per-track trim, new ArduPilot
parameters, MAVLink policy changes, new motor electronics, and changes to Unit
or Cyberbrick are explicit non-goals. The envelope should be removed once the
prototype battery/power design can safely run the motors at their intended full
range.

## References

- `docs/contracts/board-mavlink.md`
- `docs/contracts/unit-hardware-worker.md`
- `devices/common/daemon.env.template`
- `devices/tbot/ardupilot/patches/0001-linux-tbot-sysfs-pwm.patch`
- `devices/tbot/ardupilot/openrc/txing-tbot-ardupilot`

## GitHub tracking

- [Milestone 7 — TBot prototype motor output envelope](https://github.com/mparkachov/txing/milestone/7)
- [#138 — Bound TBot brushed PWM output to the configured motor envelope](https://github.com/mparkachov/txing/issues/138)
- [#139 — Load the TBot prototype motor envelope from daemon.env](https://github.com/mparkachov/txing/issues/139)
- [#140 — Ship the bounded TBot ArduPilot runtime](https://github.com/mparkachov/txing/issues/140)
- [#141 — Validate the TBot motor envelope on lifted hardware](https://github.com/mparkachov/txing/issues/141)
