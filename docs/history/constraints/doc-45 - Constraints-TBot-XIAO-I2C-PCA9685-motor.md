---
id: doc-45
title: 'Constraints: TBot XIAO I2C PCA9685 motor'
type: guide
created_date: '2026-09-08 00:00'
updated_date: '2026-09-08 00:00'
tags:
  - tbot
  - ardupilot
  - xiao
  - i2c
  - pca9685
  - drv8835
  - constraints
---

# Constraints: TBot XIAO I2C PCA9685 motor

These rules govern the TBot motor-path change described in
`doc-45 - TBot-XIAO-I2C-PCA9685-motor-architecture.md`. They supersede the
Pi-owned PWM and relay rules in `doc-38`, `doc-39`, `doc-40`, and `doc-41`,
and they supersede the host-sysfs envelope placement in `doc-43` and
`doc-44`, for TBot only.

## Ownership rules

- ArduPilot remains the exclusive TBot motor-command owner.
- The XIAO is an I2C actuator peripheral. It is not a second flight
  controller and not a return of the hardware worker or MCP.
- Motor I2C, PCA9685 emulation, and DRV8835 drive are TBot-only. Do not put
  them into the shared LM20A driver unconditionally.
- `power-nrf` product behavior, Unit hardware-worker motors, and Cyberbrick
  ArduPilot stay unchanged.
- Shared REDCON may call optional TBot-only hardware hooks. Those hooks must
  be inert when `power-nrf` does not define them.

## Hardware rules

- Keep D1 / `P1.31` as the active-high Raspberry Pi power output.
- Connect Pi I2C1 (GPIO 2/3) to XIAO D4/D5 (P1.03/P1.07).
- Drive DRV8835 PHASE/ENABLE from the XIAO. Do not leave BCM 12/13 PWM or
  BCM 5/6 direction connected to the DRV8835.
- Use D0/D2 for left ENABLE/PHASE, D3/D8 for right ENABLE/PHASE, and D10 for
  nSLEEP. Do not reuse D6/D7.
- Keep DRV8835 in PHASE/ENABLE mode.
- Both sides are 3.3 V. Do not add a level shifter or a physical PCA9685.

## Sleep and failsafe rules

- REDCON 4 keeps current D1-off and Thread SED `n` behavior.
- In REDCON 4 the I2C target is disabled and SDA/SCL are high-Z so they
  cannot back-feed an unpowered Pi.
- In REDCON 4 nSLEEP is low and PHASE/ENABLE are low.
- Firmware starts in REDCON 4. I2C and motor outputs enable only after
  REDCON 3.
- While powered, loss of I2C traffic for about 200 ms must neutralize both
  tracks.
- REDCON 4 must neutralize immediately, independent of Pi power.
- Do not claim neutralization after XIAO reset failure, motor-rail failure,
  or an unhandled firmware crash.

## ArduPilot rules

- Keep `--board linux --extra-hwdef`. Select
  `HAL_BOARD_SUBTYPE_LINUX_OBAL_V1` for stock PCA9685 on `/dev/i2c-1`
  address `0x40`.
- Do not build `--board obal` or `--board erlebrain2` as the top-level
  board.
- Do not enable `HAL_LINUX_GPIO_RPI_ENABLED` or `OBAL_ALLOW_ADC`.
- Do not keep the TBot sysfs PWM / GPIO character-device patch stack.
- The only allowed leftover C++ patch is setting the PCA9685 OE pin to `-1`
  if Empty GPIO init panics. Do not reintroduce GPIO_TBot or sysfs PWM.
- Use `MOT_PWM_TYPE=0` with SERVO1/2 throttle left/right, trim 1500, min
  1000, max 2000. Do not use BrushedWithRelay or BrushedBiPolar.
- Do not set `MOT_PWM_FREQ`. Physical ~16 kHz carrier is generated on the
  XIAO.
- Remove relay parameters. Reverse remains PHASE high.
- Keep loopback-only SERIAL1 MAVLink, GCS failsafe, and ordinary non-forced
  arming.

## Envelope rules

- Apply the prototype 480 / 100 / 200 duty policy on the XIAO, after
  converting PCA9685 pulse width to signed track command.
- Neutral stays 0% ENABLE. Every nonzero command stays in the inclusive
  min/max duty interval.
- Do not require `TXING_MOTOR_*` in `daemon.env` for ArduPilot startup.
- Changing the envelope is a firmware change until the prototype battery can
  take full duty.
- `SERVO1/2_MIN` / `MAX` may add an extra MAVLink-visible cap. They are not
  a substitute for the XIAO hard ceiling.
- Keep Unit hardware-worker envelope behavior unchanged.

## MCU and source rules

- Use the stock Zephyr `xiao_nrf54lm20a/nrf54lm20a/cpuapp` board. Do not
  fork Zephyr or add a local board definition.
- Prefer Zephyr I2C target on TWIS22. If that binding is not usable, contain
  nrfx TWIS in tbot-owned sources. Do not bit-bang PCA9685.
- If TWIS22 on D4/D5 is not viable with Thread `rn`, stop and report.
- PCA9685 emulation must accept MODE1 sleep/restart/auto-increment,
  PRE_SCALE, ALL_LED_*, and auto-incremented LED ON/OFF blocks.
- PRE_SCALE decodes pulse width only. It does not set DRV8835 carrier
  frequency.
- Keep TXN1, CoAP, SRP, battery, and SED recovery unchanged.

## Board and release rules

- TBot `usercfg.txt` enables `dtparam=i2c_arm=on` and must not enable
  `pwm-2chan`. Unit and Cyberbrick keep their PWM overlays.
- ArduPilot must not start if `/dev/i2c-1` is missing.
- Publish MCU image, ArduPilot binary, matching source archive, and OpenRC
  in the same immutable `tbot-v*` job.
- Do not publish a TBot hardware-worker asset.
- Flashing, rewiring, overlay edit, and motor energization remain manual
  operator actions.

## Compatibility rules

- Preserve the full `txing.mavlink.v1` contract: one complete MAVLink 2
  frame per binary message, byte-for-byte forwarding, and no message
  rewrite.
- Do not change shared MAVLink protobufs, schemas, Office behavior, cloud
  resources, device manifests, or public REDCON semantics.
- Do not change `power-nrf`, Unit, or Cyberbrick.

## Validation and rollout rules

- Prove automated PCA9685 decode, signed-pulse mapping, envelope floor/cap,
  REDCON 4 high-Z / nSLEEP off, I2C timeout neutralize, unchanged
  `power-nrf` builds/tests, unpatched ArduPilot Alpine build, and TBot I2C
  overlay checks.
- Perform powered tests only with the chassis lifted and secured and an
  immediate physical power cut available. Agents do not energize or drive
  hardware.
- Confirm `i2cdetect -y 1` shows `0x40` before energizing motors.

## GitHub tracking

- [Milestone 8: TBot XIAO I2C PCA9685 motor path](https://github.com/mparkachov/txing/milestone/8)
- [#143](https://github.com/mparkachov/txing/issues/143)
- [#144](https://github.com/mparkachov/txing/issues/144)
- [#145](https://github.com/mparkachov/txing/issues/145)
- [#146](https://github.com/mparkachov/txing/issues/146)
- [#147](https://github.com/mparkachov/txing/issues/147)
- [#148](https://github.com/mparkachov/txing/issues/148)
- [#149](https://github.com/mparkachov/txing/issues/149)
