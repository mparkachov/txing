---
id: doc-45
title: TBot XIAO I2C PCA9685 motor architecture
type: specification
created_date: '2026-09-08 00:00'
updated_date: '2026-09-08 00:00'
tags:
  - tbot
  - ardupilot
  - xiao
  - i2c
  - pca9685
  - drv8835
  - mcu
  - board
---

# TBot XIAO I2C PCA9685 motor architecture

## Outcome and scope

TBot stops generating DRV8835 PWM and direction on the Raspberry Pi. The Pi
talks to the XIAO nRF54LM20A over I2C. The XIAO presents the stock ArduPilot
Linux PCA9685 motor device and drives the DRV8835 only while the board is
powered (MCU transport REDCON 3). Sleep (REDCON 4) keeps the current D1 and
Thread SED behavior.

ArduPilot is built as generic Linux with an extra hardware definition that
selects an existing PCA9685 board subtype. That removes the TBot sysfs PWM and
GPIO character-device patch stack.

This design supersedes the Pi-owned PWM and relay contract in
[doc-38](doc-38%20-%20TBot-ArduPilot-DRV8835-QGroundControl-PoC-architecture.md)
and [doc-40](doc-40%20-%20TBot-MAVLink-WebRTC-control-architecture.md), and it
moves the prototype duty envelope off the host sysfs adapter described in
[doc-43](doc-43%20-%20TBot-prototype-motor-output-envelope-architecture.md).
MAVLink, Office, cloud, Unit, Cyberbrick, and `power-nrf` product behavior do
not change.

## Why this model

ArduPilot Linux already drives motors over I2C through `RCOutput_PCA9685`.
That backend is used by several Raspberry Pi hats. Bebop and Disco I2C BLDC
protocols are not a DRV8835 fit.

A physical PCA9685 chip is not required. The XIAO emulates the PCA9685
register map on `/dev/i2c-1` at address `0x40`. ArduPilot then uses an
already-supported motor device instead of TBot-specific sysfs PWM.

Do not build `--board obal` or `--board erlebrain2` as the top-level board.
Those hwdefs enable `/dev/mem` Raspberry Pi GPIO, probe IMUs and baros TBot
does not have, and in Erle-Brain 2's case expect a 24.576 MHz external clock
and a channel offset of 3. Keep `--board linux --extra-hwdef` and only borrow
the stock PCA9685 constructor by setting `CONFIG_HAL_BOARD_SUBTYPE` to
`HAL_BOARD_SUBTYPE_LINUX_OBAL_V1`.

OBAL's PCA9685 settings are the ones TBot needs:

- I2C bus 1 → `/dev/i2c-1` (Pi header SDA/SCL, GPIO 2/3)
- address `0x40` (PCA9685 default)
- internal oscillator (no external clock)
- channel offset 0 (SERVO1 is PCA9685 channel 0)
- OE pin 17, which is a no-op with Empty GPIO because the extra hardware
  definition does not enable `HAL_LINUX_GPIO_RPI_ENABLED`

`AP_HAL_Empty::GPIO::channel()` returns a dummy `DigitalSource`. OE init
writes that dummy and does not need `/dev/mem` or a TBot GPIO backend.

## Control path

```text
Office / MAVLink  →  txing-tbot-mavlink  →  ArduPilot (linux + OBAL PCA9685)
                                              │
                                              │ I2C-1, 0x40, PCA9685 registers
                                              ▼
                              XIAO nRF54LM20A (I2C target, only at REDCON 3)
                                              │
                                              │ PHASE + ENABLE at ~16 kHz
                                              ▼
                                           DRV8835
```

ArduPilot remains the exclusive motor-command owner. The XIAO is an I2C
actuator peripheral, not a second flight controller and not a return of the
hardware worker.

## Hardware

Rewire the existing DRV8835 PHASE/ENABLE connections from the Pi PWM/GPIO
header onto the XIAO. Keep DRV8835 in PHASE/ENABLE mode (MODE strapped the
same way it is today).

XIAO pin map (D1 stays Pi power):

| Function | XIAO | SoC | Notes |
| --- | --- | --- | --- |
| Pi power | D1 | P1.31 | Unchanged. Active-high. |
| I2C SDA | D4 | P1.03 | Stock XIAO I2C. Pi GPIO 2. |
| I2C SCL | D5 | P1.07 | Stock XIAO I2C. Pi GPIO 3. |
| Left ENABLE (PWM) | D0 | P1.00 | ~16 kHz |
| Left PHASE | D2 | P1.30 | GPIO |
| Right ENABLE (PWM) | D3 | P1.29 | ~16 kHz |
| Right PHASE | D8 | P1.04 | GPIO |
| DRV8835 nSLEEP | D10 | P1.06 | Active-high. Low in REDCON 4. |

Do not use D6/D7; those are the XIAO serial pins used by debug images.

Pi side:

- Enable `dtparam=i2c_arm=on` in `/boot/usercfg.txt`.
- Remove TBot's `dtoverlay=pwm-2chan,...` line. Unit and Cyberbrick keep
  their PWM overlays.
- Disconnect BCM 12/13 PWM and BCM 5/6 direction from the DRV8835.
- Both sides are 3.3 V. Use the Pi I2C1 pull-ups while the Pi is powered.

When the Pi is unpowered, those pull-ups are unpowered. XIAO I2C pins must
be high-Z in REDCON 4 so they cannot back-feed the Pi through SDA/SCL.

## Sleep and REDCON

| MCU transport | D1 / `led0` | Thread | I2C target | DRV8835 |
| --- | --- | --- | --- | --- |
| REDCON 4 (default, sleep) | off | SED `n`, 5000 ms poll | disabled, pins high-Z | nSLEEP low, PHASE/ENBL low |
| REDCON 3 (power on) | on | `rn` | enabled at 0x40 | nSLEEP high; motors follow I2C, default neutral |

Public REDCON 1/2/3 still map to MCU transport 3. Public REDCON 4 still maps
to transport 4. CoAP, SRP, TXN1, battery, and SED recovery stay as they are.

Firmware still starts in REDCON 4. I2C and motor outputs come up only after
a successful REDCON 3, which is before the Pi boots, so the target is present
when ArduPilot opens `/dev/i2c-1`.

If I2C traffic stops while powered (ArduPilot crash, bus hang), the XIAO
must neutralize both tracks after a short timeout (about 200 ms). REDCON 4
neutralizes immediately, independent of Pi power.

## ArduPilot

Keep the disposable clean-upstream checkout and
`--board linux --extra-hwdef`. The TBot extra hardware definition selects the
stock PCA9685 path and keeps the no-sensor accommodations:

```text
define CONFIG_HAL_BOARD_SUBTYPE HAL_BOARD_SUBTYPE_LINUX_OBAL_V1
define HAL_INS_DEFAULT HAL_INS_NONE
define AP_INERTIALSENSOR_DUMMY_BACKEND 1
define HAL_BARO_ALLOW_INIT_NO_BARO 1
define AP_HAL_LINUX_SET_HW_RTC_ENABLED 0
```

Do not enable `HAL_LINUX_GPIO_RPI_ENABLED` or `OBAL_ALLOW_ADC`. AnalogIn stays
Empty. GPIO stays Empty. RCOutput is `RCOutput_PCA9685` on bus 1 address 0x40.

Delete `devices/tbot/ardupilot/patches/0001-linux-tbot-sysfs-pwm.patch` and
the `ardupilot::patch` step if no C++ patch remains. Residual risk: if OE
init ever panics on Empty GPIO, the only allowed leftover patch is setting
that constructor's OE argument to `-1`. Do not reintroduce GPIO_TBot or
sysfs PWM.

Upstream ArduPilot now defines `HAL_BOARD_SUBTYPE_LINUX_SYSFS_PWM` as 1032,
which collides with TBot's patched subtype number. Moving off that patch is
required for a clean live-master checkout.

### Motor parameters

PCA9685 is a servo-style command interface. Its period must stay large enough
for 1000–2000 µs pulses (50 Hz default). Rover `MOT_PWM_TYPE=3` or `4` also
calls `set_freq(16 kHz)`, which overflows the PCA9685 12-bit width math.
Physical 16 kHz carrier belongs on the XIAO, not on the I2C command frame.

Use stock signed servo pulses:

```text
MOT_PWM_TYPE       0
SERVO1_FUNCTION    73
SERVO1_MIN         1000
SERVO1_TRIM        1500
SERVO1_MAX         2000
SERVO2_FUNCTION    74
SERVO2_MIN         1000
SERVO2_TRIM        1500
SERVO2_MAX         2000
```

Remove `RELAY1_*` / `RELAY2_*`. Leave `MOT_PWM_FREQ` unset so PCA9685 stays
at its 50 Hz init. XIAO maps channel 0/1 pulse width to DRV8835 PHASE+ENABLE:

- 1500 µs → stop (ENABLE 0)
- >1500 µs → forward, duty from distance above trim
- <1500 µs → reverse, PHASE high, duty from distance below trim

Direction convention stays the current one: reverse is PHASE high.

MAVLink, SERIAL1 `udpin:127.0.0.1:14550`, GCS failsafe, arming skip, and
OpenRC service identity stay as they are.

## Prototype motor envelope

The envelope in the sysfs patch and OpenRC `daemon.env` export cannot stay in
ArduPilot once sysfs PWM is gone. Move the same 480 / 100 / 200 policy onto
the XIAO, which now owns the physical duty.

- Neutral stays 0% ENABLE.
- Every nonzero command is mapped into the inclusive min/max duty interval
  (~20.8%–41.7% with the current numbers).
- Changing the envelope is a firmware change until the prototype battery can
  take full duty. Do not keep ArduPilot startup dependent on
  `TXING_MOTOR_*` in `daemon.env`.
- Optional extra cap through `SERVO1/2_MAX` / `MIN` remains available over
  MAVLink; it is not a substitute for the XIAO hard ceiling.

Unit hardware-worker envelope behavior is unchanged.

## MCU firmware ownership

`power-nrf` and `tbot` share `devices/common/mcu/xiao_nrf54lm20a/src/thread_device.c`.
Motor I2C and DRV8835 code is TBot-only.

- Add tbot sources under `devices/tbot/mcu/src/` and a tbot overlay for I2C
  target, PWM, and motor GPIOs.
- `devices/tbot/mcu/zephyr/CMakeLists.txt` compiles those extra sources.
- Shared `thread_device.c` gets weak hooks called from REDCON 3/4.
  `power-nrf` does not define them.
- Do not put motor code, I2C target, or PWM into the shared LM20A driver
  unconditionally.
- Do not fork the stock Zephyr tree. Prefer Zephyr I2C target
  (`nordic,nrf-twis`) on TWIS22 using D4/D5. If that binding is not usable on
  this SoC, contain nrfx TWIS in tbot-owned sources. PMIC I2C and IMU I2C stay
  on their own buses.

PCA9685 emulation must accept the writes ArduPilot actually sends: MODE1
sleep/restart/auto-increment, PRE_SCALE, ALL_LED_*, and auto-incremented LED
ON/OFF blocks. Physical PWM frequency is local to the XIAO; PRE_SCALE is used
only to decode pulse width.

## Board runtime

TBot-only changes:

- Board runbook step 5: TBot enables `dtparam=i2c_arm=on` instead of
  `pwm-2chan`. Fail ArduPilot start if `/dev/i2c-1` is missing.
- OpenRC: drop the three `TXING_MOTOR_*` required exports.
- `just tbot::ardupilot::test` / `build`: configure linux extra-hwdef without
  applying the sysfs patch; drop `tests/test_rcoutput_sysfs_brushed`.
- Release: the next `tbot-v*` publishes new MCU image, ArduPilot
  binary/source, and OpenRC/docs together. KVS/daemon/MAVLink binaries change
  only if their sources must change.

No cloud, shadow, MQTT, Office, rig, or MAVLink frame-contract changes.

## Risks

- nRF54LM20A I2C target while Thread `rn` is running is the first hardware
  spike. If TWIS22 on D4/D5 is not viable, stop and report; do not bit-bang a
  fake PCA9685 on GPIO.
- I2C back-power of an unpowered Pi if REDCON 4 leaves SDA/SCL driven.
- Motors can still run after Pi power-cut unless the XIAO explicitly
  deasserts nSLEEP / ENABLE. That is required, and it is safer than today's
  floating Pi PWM pins.
- Empty GPIO OE no-op: confirm ArduPilot starts without `/dev/mem`.
- PCA9685 at 16 kHz would corrupt pulse encoding; that is why command PWM
  stays 50 Hz and the carrier stays on the XIAO.
- Prototype envelope becomes a firmware constant. Operators who currently
  edit `daemon.env` and restart ArduPilot will need a firmware rebuild
  instead.

## Non-goals

- Physical PCA9685 chip, or any extra I2C expander.
- Returning the TBot hardware worker or MCP.
- Changing Unit, Cyberbrick, or `power-nrf` motor/power behavior.
- Floor driving, IMU/GPS fusion, or a crash-time hardware watchdog beyond
  XIAO I2C timeout plus REDCON 4 neutralize.
- `/dev/mem` GPIO, Debian, or a non-linux ArduPilot board.
- Cloud, shadow, Office, or MAVLink protocol changes.
- Automated flashing, AWS mutation, or git commit.

## Validation

Automated:

- TBot MCU: PCA9685 register decode, signed pulse → PHASE/ENABLE mapping,
  envelope floor/cap, REDCON 4 high-Z / nSLEEP off, I2C timeout neutralize.
- Shared LM20A / `power-nrf` SED, factory, and profile tests still pass.
- TBot ArduPilot Alpine configure/build with the new extra-hwdef and no
  sysfs patch; `--help`; static aarch64 assertions.
- Board overlay/OpenRC checks: TBot has i2c_arm, not pwm-2chan; Unit still
  has pwm-2chan.
- Existing MAVLink golden-frame and Office adapter tests unchanged.

Manual (chassis lifted, motor power isolated until commanded):

1. Flash tbot firmware. Confirm REDCON 4: D1 off, motors off, SED `n`.
2. REDCON 3: D1 on, `i2cdetect -y 1` shows `0x40`.
3. Start ArduPilot. Parameter download works. SERVO1/2 are throttle left/right
   with trim 1500. No RELAY pins.
4. Arm, forward/reverse through neutral, differential turns, joystick release
   → stop, GCS-loss Hold, OpenRC stop → stop.
5. Duty stays inside the prototype envelope.
6. REDCON 4 while moving → motors off, D1 off, I2C pins not back-feeding.
7. Reboot: ArduPilot starts, worker remains absent, PWM overlay remains absent.

## Rollout

1. Isolate motor power. Rewire DRV8835 to the XIAO. Connect Pi I2C1 to D4/D5.
2. `just tbot::mcu::build` then the operator flashes
   (`just tbot::mcu::flash`).
3. On the board: root-writable, set `dtparam=i2c_arm=on`, remove TBot
   `pwm-2chan`, reboot.
4. Publish/install the next `tbot-v*` ArduPilot plus matching source archive
   and OpenRC file. Restart in the existing order: ArduPilot, mavlink, daemon,
   KVS.
5. Confirm `/dev/i2c-1` and address `0x40` before energizing motors.

Agents do not flash, do not energize motors, and do not commit unless asked.

## Tracking

- [Milestone 8: TBot XIAO I2C PCA9685 motor path](https://github.com/mparkachov/txing/milestone/8)
- [#143: Publish the TBot XIAO I2C motor and sleep contract](https://github.com/mparkachov/txing/issues/143)
- [#144: Keep power-nrf unchanged while TBot REDCON can enable motor hardware](https://github.com/mparkachov/txing/issues/144)
- [#145: Drive TBot tracks from the XIAO only while the board is powered](https://github.com/mparkachov/txing/issues/145)
- [#146: Command TBot motors through stock Linux PCA9685 I2C](https://github.com/mparkachov/txing/issues/146)
- [#147: Boot TBot with I2C to the XIAO instead of Pi PWM](https://github.com/mparkachov/txing/issues/147)
- [#148: Ship the TBot I2C motor runtime](https://github.com/mparkachov/txing/issues/148)
- [#149: Validate TBot I2C motor control on lifted hardware](https://github.com/mparkachov/txing/issues/149)

## References

- `docs/history/architecture/doc-38 - TBot-ArduPilot-DRV8835-QGroundControl-PoC-architecture.md`
- `docs/history/architecture/doc-40 - TBot-MAVLink-WebRTC-control-architecture.md`
- `docs/history/architecture/doc-43 - TBot-prototype-motor-output-envelope-architecture.md`
- `docs/history/architecture/tbot-thread-device-architecture.md`
- `docs/components/mcu.md`
- `docs/components/board.md`
- `devices/tbot/README.md`
- `devices/common/board/ardupilot/libraries/AP_HAL_Linux/RCOutput_PCA9685.cpp`
