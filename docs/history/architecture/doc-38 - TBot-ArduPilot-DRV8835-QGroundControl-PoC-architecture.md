---
id: doc-38
title: TBot ArduPilot DRV8835 QGroundControl PoC architecture
type: specification
created_date: '2026-08-26 00:00'
updated_date: '2026-08-26 00:00'
tags:
  - ardupilot
  - tbot
  - drv8835
  - qgroundcontrol
  - board
  - alpine
---

# TBot ArduPilot DRV8835 QGroundControl PoC architecture

## Outcome and scope

TBot gains an optional ArduRover runtime that can directly drive its existing
DRV8835-connected tracks from QGroundControl joystick commands over MAVLink 2
UDP. This milestone proves the physical control path on a safely lifted TBot;
it does not replace or integrate with TBot's normal daemon and hardware-worker
control path.

The hardware worker remains enabled in the OpenRC default runlevel and
ArduPilot remains disabled there. For each proof-of-concept session, the
operator manually stops the hardware worker and starts ArduPilot. Reversing the
sequence restores normal operation, and reboot also restores the normal worker
path. There is no automatic service switching or service-level mutual-exclusion
guard.

The daemon and KVS master remain running while ArduPilot owns the motors. The
daemon uses its existing worker-unavailable behavior; the TBot manifest,
capabilities, gRPC APIs, MQTT topics, Thing Shadows, MCP behavior, Office, and
cloud resources do not change.

## Source and patch workflow

`devices/common/board/ardupilot/` remains the ignored, disposable clone of live
upstream ArduPilot `master`, including submodules. Clean upstream is the sole
source baseline: the TBot build does not depend on a Cyberbrick fork, an
unmerged upstream pull request, or source copied from Cyberbrick's patch stack.
TBot owns an independent ordered patch stack under `devices/tbot/ardupilot/`
and never reads or changes patches in the Cyberbrick device directory.

A shared checkout carries exactly one device patch stack. Switching between a
Cyberbrick and TBot build means manually discarding the ignored checkout and
cloning it again; there is no update, repair, rollback, or combined-patch
workflow. The TBot patch set is limited to the Linux hardware adaptation that
upstream does not yet provide for this board. It introduces:

- a Linux TBot board subtype selected by the TBot hardware definition;
- the same no-IMU and no-barometer accommodation used by the Linux Cyberbrick
  proof of concept, implemented against the clean upstream baseline without a
  Cyberbrick source dependency;
- selection of upstream Raspberry Pi GPIO for the two ArduPilot relay outputs;
- brushed-mode duty scaling in the existing Linux sysfs RC-output backend and
  focused coverage of its output-mode, range, and frequency behavior.

There is no TBot-specific motor mixer, signed-output convention, direction
parameter family, or DRV8835 RC-output backend. ArduRover's standard
`BrushedWithRelay` motor mode owns those semantics.

The public TBot Just interface is:

- `ardupilot::checkout` for the recursive live-master clone;
- `ardupilot::patch` for the ordered TBot patch stack;
- `ardupilot::build` for the already-patched checkout.

## DRV8835 output contract

ArduPilot owns two PWM channels and two physical direction lines while it runs:

| Track | PWM | Direction |
| --- | --- | --- |
| Left | `pwmchip0/pwm0` | BCM GPIO `5` |
| Right | `pwmchip0/pwm1` | BCM GPIO `6` |

Both tracks use normal polarity with no compile-time inversion. The tracked
defaults select standard ArduRover brushed-with-relay behavior:

```text
MOT_PWM_TYPE       3
SERVO1_FUNCTION    73
SERVO2_FUNCTION    74
RELAY1_FUNCTION    5
RELAY1_PIN         5
RELAY2_FUNCTION    6
RELAY2_PIN         6
```

`MOT_PWM_FREQ` is not overridden by TBot defaults. Upstream therefore starts
from its 16 kHz brushed-motor default. The parameter remains visible and
changeable through the ordinary MAVLink parameter protocol, including
QGroundControl, within upstream's supported `1..20 kHz` range; applying a
change requires an ArduPilot restart.

In mode 3, ArduRover sets each direction through its standard brushed-reverse
relay function, converts signed throttle to a nonnegative magnitude, and sends
that magnitude to the corresponding servo output. The Linux sysfs RC-output
adaptation honors `MODE_PWM_BRUSHED`: values at or below ArduPilot's configured
ESC minimum become 0% duty, values at or above its ESC maximum become 100%
duty, and intermediate values are linear. There is no `1500 us` neutral or
TBot-owned signed mapping. Reverse drives the direction line high; neutral and
forward drive it low, matching the hardware worker's direction convention.

The proof of concept deliberately uses upstream motor and relay behavior
without adding TBot-specific direction-change sequencing. Powered acceptance
returns the command to neutral before selecting the opposite direction. The
TBot defaults retain upstream's zero minimum throttle and full maximum throttle
rather than copying the hardware worker's power cap or minimum nonzero command.

Initialization, channel disable, `force_safety_on`, and graceful process exit
neutralize both channels. A GPIO or PWM initialization/write failure first
attempts to neutralize both outputs and then terminates ArduPilot so OpenRC can
report and supervise the failure. This is not a crash-time hardware watchdog:
`SIGKILL`, kernel failure, or a process crash during a hardware write can leave
the kernel's last PWM state active until another owner reinitializes it.

## ArduRover and QGroundControl behavior

Only ArduRover is built. TBot's tracked defaults configure left and right
throttle functions on outputs 1 and 2, Manual as the initial mode, Hold as the
safe mode, no RC receiver, no physical safety switch, and the minimum no-sensor
arming accommodations needed for ordinary QGroundControl arming. Forced arming
is not part of the acceptance path.

SERIAL0 carries MAVLink 2 and listens at `udpin:0.0.0.0:14550`. QGroundControl
uses its standard system ID `255`, emits its normal heartbeat, and creates a UDP
link whose remote host is the TBot's LAN address and port `14550`. GCS failsafe
uses a one-second timeout and Hold action so loss of the QGroundControl link
returns the tracks to neutral.

The endpoint is unsigned, unauthenticated, and reachable on every board network
interface. This is permitted only on a trusted isolated LAN for the PoC.
Firewall policy, MAVLink signing, a txing MAVLink service, WebRTC, Office, and
remote/cloud control are future work.

## Build, release, and runtime

The TBot Linux target builds statically in the repository's pinned Alpine
3.24.1 native arm64 environment using ArduPilot's stock Alpine prerequisite
installer, `waf configure --board linux --extra-hwdef ... --static`, and
`waf rover`.

The `tbot-v0.18.0` release adds:

- `txing-tbot-ardupilot-linux-aarch64.tar.gz`, containing the root-level
  `txing-tbot-ardupilot` executable and its tracked defaults file;
- `txing-tbot-ardupilot-source.tar.gz`, containing the exact patched source
  from the same job, initialized submodules, upstream license, and build
  instructions.

The release records the upstream SHA and retains the existing static aarch64
ELF, no-interpreter, `--help`, license, and archive-shape assertions. The source
asset, rather than a pinned checkout recipe, preserves the corresponding source
for each immutable release.

The board installs ArduPilot through a separate root-owned mise tool entry and
an OpenRC service named `txing-tbot-ardupilot`. The service listens on UDP
14550 and uses tmpfs-backed storage and terrain under
`/var/tmp/txing-tbot-ardupilot/` with logs under
`/var/log/txing-tbot-ardupilot/`. It is installed but not added to the default
runlevel. A service catalog entry is included in future board daemon bundles,
but adopting it does not replace the existing private TBot daemon environment
or certificates.

## Manual ownership and acceptance

The operator keeps motor power isolated while installing and starting the new
runtime, then performs this ownership sequence:

1. disarm, isolate motor power, and stop `txing-tbot-hardware-worker`;
2. verify the worker process is stopped and the tracks are neutral;
3. start `txing-tbot-ardupilot` and verify its service and UDP endpoint;
4. connect QGroundControl and confirm telemetry and parameter download;
5. lift and secure the chassis, confirm neutral, and only then energize motors;
6. arm normally and demonstrate both tracks forward/reverse through neutral,
   differential turns, the full selected duty range, neutral on joystick
   release and disarm, GCS-loss Hold, and neutral on graceful OpenRC stop;
7. restart the hardware worker and confirm local actuator readiness;
8. reboot and confirm the worker starts while ArduPilot remains stopped.

The operator must never start the two motor owners together. No floor driving,
autonomous navigation, GPS/IMU integration, missions, durable ArduPilot state,
or hard-crash neutralization claim is part of milestone acceptance.

## References

- `docs/history/architecture/doc-34 - Cyberbrick-ArduPilot-board-runtime-architecture.md`
- `docs/contracts/unit-hardware-worker.md`
- `devices/common/board/hardware_worker/src/motor.cpp`
- [ArduPilot Linux startup options](https://ardupilot.org/dev/docs/ardupilot-on-linux-starting.html)
- [QGroundControl communication links](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/comm_links.html)
