# Virtual quadcopter

`virtual-quad` is a cloud rig device type with disposable ARM64 ArduCopter
SITL sessions. Office operates the simulator and displays its onboard camera
and MAVLink telemetry. The shared agent can observe or take explicit
manual control through the device's MAVLink lease.
[Architecture and ownership](../../docs/virtual-quadcopter-architecture.md)

## Enlistment

Deploy the shared AWS stack to register the `virtual-quad` type and publish
the corresponding [cloud rig Lambda release](../cloud-mcu/README.md#aws-deploy-and-runtime-publish).
Enlist the device on an existing cloud rig.

```sh
just aws::deploy-device <cloud-rig-id> virtual-quad virtual-quad
```

The permanent registration in the `town` environment is
[`aws → virtual-quad`](https://office.txing.dev/town-jhgjjd/cloud-8lgj1r/virtual-quad-1knemq).
Its Thing ID is `virtual-quad-1knemq`. Use the existing registration when
updating that environment. Each registered device has its own session
record and signaling channels.

The enlist operation creates the Thing, the five named shadows and the
device's `-board-video` and `-mavlink` signaling channels. The
[manifest](manifest.toml) identifies the shadow contracts, with examples
in [fixtures](aws/fixtures/).

The next awake cloud rig census announces the device at REDCON 4 with
Sparkplug available and simulation inactive. Office lists it under the assigned rig
and enables REDCON 1 while the rig reports awake. Enlistment and the stopped
census use neither simulator nor observer compute.

## Build and publish the session Lambda

Build the ARM64 release ZIP with Apple Container from the repository root:

```sh
just virtual-quad::lambda-package
```

The recipe prints the ZIP path. The shared Lambda release workflow publishes
the same payload with the other immutable runtime artifacts. Publish the
reviewed Lambda release through `just release::publish lambda`; see
[Lambda publication](../../docs/aws.md#deploy-and-publish) for the
shared release process. Bump `release/versions/lambda` to a new version
before publishing this change; `0.15.14` has already been released.

Qualify the actual release ZIP before changing the permanent device. The
isolated `lambda/qualification.template.yaml` creates disposable channels and
runs the production supervisor on ARM64 Lambda. Invoke the function twice,
including `{"durationSeconds":720}` for a full-duration run. Check startup,
native library loading, both KVS streams, video and SITL performance, fresh
state in the reused execution environment, and child reaping. Record the ZIP
checksum, logs and media measurements in the implementation Issue and remove
the disposable resources after qualification.

For isolated lifecycle checks, `lambda/lifecycle-qualification.template.yaml`
uses a manually created disposable device and creates its channels, function,
scoped IoT command and shadow rules, and an EventBridge failure route. It uses an existing awake cloud rig,
but sends test commands on a separate qualification topic so the production
simulator controller cannot receive them. Seed its `simulation` and
`sparkplug` shadows before testing. To exercise the shared agent and Office,
declare the `agent` capability on the disposable Thing and initialize the
`agent`, `mavlink` and `video` shadows too. Stop and drain the observer, then
delete the test shadows, Thing and stack afterward. Verify the permanent-device
command route and cutover on the target registration as described below.

### Cutover and rollback

The `town` stack was updated on 2026-11-25 and its function was updated to
`lambda-v0.15.16` on 2026-11-26. The virtual-quad ZIP SHA-256 is
`ea5846c489c30506f427c6a43268f347cc936251f64485c704784cf93e8e63d1`.
Permanent-device flight, agent handoff and retirement evidence is tracked in
[#193](https://github.com/mparkachov/txing/issues/193). The old simulator image
and retained session table were retired after the live checks. Two earlier
agent replacements were not reproduced in the updated release's monitored
viewer-join retest; their precise cause remains unconfirmed.

With the virtual quad at REDCON 4 and its agent drained, publish the compatible
Lambda release and update the function stack in the same maintenance window:

```sh
just virtual-quad::deploy
```

The stack keeps the existing function name, Thing and channels. After the live
acceptance below, verify zero simulator and observer compute, no simulator
provisioned concurrency and no dedicated scheduled invocations. Manually
retire the old simulator MicroVM image and retained DynamoDB table only after
acceptance. Keep the previous release and infrastructure template until then.
To roll back, drain the device again and restore the prior function release
and prior infrastructure template together, then verify REDCON 4 → 1 → 4.
For this `town` cutover, the previous deployed quad artifact matched
`lambda-v0.15.13`, and its stack template matched the template at commit
`ff08dc70bdd7e5b63093177417b688ff33029c60`. Restoring the shared release also
changes the other shared Lambda functions and requires their regression checks.
After the old simulator image or retained table is retired, that rollback
requires recreating the retired resources first.
The agent and TBot hosting are unchanged. KVS can charge for channels used
earlier in the billing month.

## Live media

The onboard camera uses the current SITL truth pose to render a 640 × 360
view at 15 fps. REDCON 2 indicates that the worker has a fresh SITL heartbeat
and a MAVLink signaling master. Office can open its MAVLink peer at REDCON 2
and opens its video peer at operational REDCON 1. Session changes and readiness
expiry close both peers.

If a KVS master disconnects, Office withdraws the affected capability. The
controller gives the masters up to 30 seconds to reconnect while the worker
continues to report fresh SITL heartbeat and navigation. Missing worker
health or unhealthy SITL retains the 15-second cutoff.

## Diagnostics

The qualification stack and CloudWatch logs expose `QUAD_READY`,
`QUAD_MEDIA_SAMPLE`, and `QUAD_CHILDREN_REAPED` for startup, media rate and
shutdown checks.

The local Office development page at `/virtual-quad-diagnostics.html` uses
the registered device's channels and the shared KVS viewer. Sign in through
local Office in the same tab, then open the page with `?device=<device-id>`.
Use Force TURN to record relay candidates. The page samples decoded video
and MAVLink in five-second windows. For pose-to-display timing, use the
session's `QUAD_CAMERA_RTP_EPOCH` in milliseconds and a synchronized browser
that exposes RTP timestamps in video callbacks. Download samples for
per-frame timing, decoded fps, heartbeat and flight observations.

## Flight in Office

On the selected device route, select REDCON 1 to start and REDCON 4 to stop.
The REDCON indicator and countdown show startup and shutdown progress.
The `simulation` badge turns green once the current worker reports a fresh
SITL heartbeat. It turns gray when the controller accepts Stop or its
published health window expires. Debug shows the `simulation` session
shadow at every REDCON level, including the last result after shutdown.
The Session Log records simulator startup completion and the end of a
session observed on the open page. Failures also open a notification.
When you open an already stopped device, REDCON 4 shows its state.

At REDCON 2, Office can connect to MAVLink in **View only**. The MAVLink
indicator in the video overlay reports the browser peer's connection and heartbeat
status. At REDCON 1, Office also opens the camera and enables flight actions
as soon as the browser receives fresh telemetry and video.

Each connection starts in **View only**. With live camera and MAVLink telemetry,
select **Acquire control** in the video overlay to reserve the free lease.
**Take off** selects
Guided mode, arms through the normal checks, and climbs to 2 m. Open **Debug**
for camera status, mode, arm and landed state, altitude, heading, and speed in
the **ArduPilot / MAVLink** panel.

Use the keyboard shortcuts or a connected gamepad to fly. Select
**On-screen controller** in the video overlay to show the virtual
sticks and flight buttons. Centering the sticks
commands a hover. Use **Land** and check for **Landed** and **Disarmed** in
the telemetry. **Release control** returns to View only.
[Office controller mapping](../../docs/components/office.md#mavlink-controller)

The simulator grants one five-second renewable lease. Two seconds without
a decoded camera frame cause Office to release the lease. Release, peer
disconnect, lease expiry, and session Stop close the simulator's write gate
and request LAND if the aircraft may be airborne. Reconnecting opens a new
View only peer.


## Permanent deployment acceptance

Review the [architecture](../../docs/virtual-quadcopter-architecture.md) and
the build and publication evidence first. Open
[`aws → virtual-quad`](https://office.txing.dev/town-jhgjjd/cloud-8lgj1r/virtual-quad-1knemq)
on the mixed rig and confirm the following.

1. The registered device is visible and startable at stopped REDCON 4 with
   no active simulator invocation or observer VM. Confirm its two registered KVS channels.
2. Select REDCON 1. Record readiness and command outcomes across three cold
   starts. Startup is bounded to 90 seconds. Record the actual ready, stop
   and terminal timestamps.
3. Confirm camera and heartbeat, take control, take off to 2 m, translate,
   climb, yaw, hover, land and release control. Use a second viewer to check
   exclusive control. Inspect both streams in Agent Debug. After releasing
   Office control, attach the agent with `--control` and verify that
   QGroundControl reads parameters while the simulator is disarmed. For a
   button-only flight check, disable the physical joystick and the separate
   **Virtual joystick** setting in QGroundControl before using **Takeoff** and
   **Land**. Joystick throttle input can trigger ArduCopter's RC3 neutral
   arming check. Record relay media performance with the diagnostics page.
   [QGroundControl Fly View settings](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/fly_view.html#virtual-joystick)
4. Verify a normal stop, stop during startup, flight deadline and readiness
   loss recovery. Check that the old session cannot regain authority and
   that restart allocates a new session with a fresh disarmed aircraft.
   Verify the simulator invocation and agent observer terminate and the respective
   shadows clear their active IDs.
5. Check applicable cloud rig and existing device regressions. Retain the
   [prior acceptance and approved hardware skips](https://github.com/mparkachov/txing/issues/182)
   with the new evidence.

Use these bounds for the permanent device checks.

| Area | Evidence |
| --- | --- |
| Startup and teardown | Three cold starts reach operational within 90 seconds. Healthy Stop from startup or operational reaches terminal state within 30 seconds. Abrupt termination withdraws readiness within 15 seconds of the last health report and the failure destination records the matching outcome; a lost event permits restart after the old invocation deadline. |
| Flight | Take off to 2 m ± 0.5 m, translate at least 1 m on both horizontal axes, change altitude by at least 0.5 m, yaw at least 45°, and hover within 0.5 m horizontally and vertically over five seconds after settling. Verify landed and disarmed. |
| Media | With operator and observer joined, sustain 640 × 360 and at least 12 decoded fps in 95% of five-second windows for a full-duration session. Measure p95 pose-to-display below 800 ms and a SITL rate of 0.95–1.05× wall time over rolling 30-second windows. Include forced relay and late joins across the five-minute TURN and ten-minute signaling windows. |
| Authority loss | Confirm old writes fail and LAND begins within two seconds of server-side revocation. A silently disconnected browser loses its lease within five seconds of its last successful renewal. Check touchdown and disarm in a healthy simulator, and verify terminal cleanup at the session deadline. |
| Agent and restart | The agent receives both streams in observation mode. Explicit control can transfer a free lease and read parameters before arming. Stop, expiry, crash and rapid restart clear the old agent assignment and lease. |

[Milestone 11](https://github.com/mparkachov/txing/milestone/11)
· [Prior verification](https://github.com/mparkachov/txing/issues/182)
