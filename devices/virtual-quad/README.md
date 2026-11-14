# Virtual quadcopter

`virtual-quad` is a cloud rig device type with disposable ARM64 ArduCopter
SITL sessions. Office operates the simulator and displays its onboard camera
and MAVLink telemetry. The existing agent can join as a read-only observer.
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
Sparkplug and simulation available. Office lists it under the assigned rig
and enables REDCON 1 while the rig reports awake. Enlistment and the stopped
census use neither simulator nor observer compute.

## Build and publish the session image

Run from the repository root with the existing Lima ARM64 engine. For
publication, build from the reviewed source revision.

```sh
bundle=$(just virtual-quad::microvm-package)
```

The command tests the Go supervisor and the native camera and flight code,
builds the ARM64 payload, and validates the final image and snapshot-safe
OpenSSL linking in Lima. The final image defaults to the managed lifecycle
hook listener. It begins a simulation only after a session claim. The recipe
prints the absolute ZIP path. Keep the bundle, both adjacent source archives
and `SHA256SUMS` together. The bundle records the repository revision and
source status, native package versions, pinned ArduCopter commit and recursive
submodule revisions, the KVS SDK commit and license, and source archive digests.
The SDK pins its producer and PIC dependencies to v1.6.1 and v1.3.1. Container base
digests and dependency pins live in [runtime](runtime/). System package versions
are recorded at build time. The ArduCopter archive contains the corresponding
source and licenses for the pinned checkout and its submodules.

For a new environment, deploy the shared AWS stack and run
`just virtual-quad::deploy disabled` to prepare the session table, build role
and log group before the first image exists. Use the environment's configured
AWS profile and `TXING_AWS_STACK`. [Environment deployment](../../docs/aws.md#bring-up-order)

```sh
just virtual-quad::publish-image "$bundle"
```

The publisher discovers the shared artifact bucket and build role, checks the
ARM64 `al2023-1` managed base major version 3, and uploads the bundle and
source archives to their SHA-256 prefix. It submits the hooks from the bundle.
The result identifies the exact image ARN and version. Inspect that pair until
the build is `SUCCESSFUL` and the version is `ACTIVE`. AWS reports the
resolved base version including its patch level.

```sh
aws lambda-microvms get-microvm-image-version --region eu-central-1 \
  --image-identifier <image-arn> --image-version <image-version> \
  --query '{state:state,status:status,base:baseImageVersion,reason:stateReason,artifact:codeArtifact.uri}'
```

AWS makes successful builds active automatically. The controller omits the
image version in new launch requests, so the next Start uses the latest
active version. Image publication needs no CloudFormation deployment.
Running simulator sessions keep their current image.
[AWS MicroVM launch behavior](https://docs.aws.amazon.com/lambda/latest/dg/microvms-launching.html)

For the first installation, stage the compatible controller bootstrap with
the [Lambda publisher](../../docs/artifacts.md#lambda-artifacts), then enable
the controller after the image is active. An existing installation using
a fixed image version needs a one-time migration. Publish `lambda-v0.15.12`
or later with the existing controller deployed, then run the same command
to remove the old CloudFormation version parameter and environment setting.

```sh
just virtual-quad::deploy enabled
```

For `town`, verify the deployed controller and the image selected by AWS:

```sh
aws lambda get-function-configuration --region eu-central-1 \
  --function-name town-virtual-quad \
  --query '{state:State,update:LastUpdateStatus,code:CodeSha256,architectures:Architectures}'
aws lambda-microvms get-microvm-image --region eu-central-1 \
  --image-identifier arn:aws:lambda:eu-central-1:453102798330:microvm-image:town-virtual-quad \
  --query '{state:state,latest:latestActiveImageVersion}'
```

Confirm the controller is active and compare `CodeSha256` with the
base64-encoded SHA-256 of the controller ZIP for the selected Lambda release.
Use `get-microvm` on the running instance to verify the actual image version
used in acceptance. Record the source revision, bundle digest and S3 URI,
image ARN/version and resolved base, controller release and code digest,
agent release and image version, and Office release or deployment commit.
The existing `agent-v0.1.3` and Office `0.18.7` support the consolidated
simulator. [Office publication](../../docs/components/office.md#cloudflare-pages)

## Drain and rollback

Pause new starts during maintenance. Select REDCON 4 for each active virtual
quad, including any still starting. Wait until the simulation shadow clears
its session ID and the agent shadow clears its run and endpoint. Confirm both
MicroVMs are `TERMINATED` in the image inventories. Keep the command rule,
controller and repair schedule enabled while sessions drain.

For an image rollback, keep the previous working ARM64 version active
with its bundle and deactivate the faulty version on the MicroVM image.
Then verify `latestActiveImageVersion` before starting a new session.
For example, to fall back from 8.0 to 7.0 in `town` when 8.0 is the only
newer active version:

```sh
aws lambda-microvms update-microvm-image-version --region eu-central-1 \
  --image-identifier arn:aws:lambda:eu-central-1:453102798330:microvm-image:town-virtual-quad \
  --image-version 8.0 --status INACTIVE
```

For a controller rollback, use `just release::publish lambda <previous-release>`
only when rolling back the shared Lambda release is intended, since it also
updates the other targets. Releases before `lambda-v0.15.12` require the old
controller template with an explicit image version. Check the controller's
code digest against the selected release. Roll back Office through Cloudflare
Pages. Follow the [agent drain and release procedure](../../docs/components/agent.md#enable-and-drain)
when rolling back the shared observer.

To disable simulator launches after draining, run
`just virtual-quad::deploy disabled`. This removes the controller, command
rule and repair schedule. The build resources, session table, Thing and
channels remain available for re-enablement. Use
`just virtual-quad::deploy enabled` to restore the controller.

## Retire the temporary deployment

Use the [retirement procedure](retirement.md) once the permanent device
passes acceptance. The temporary rig/device and standalone feasibility stack
have separate ownership and cleanup sequences.

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

After packaging, run `just virtual-quad::runtime-smoke` to exercise the
production image's SITL, pose camera and encoder with no network. Compare
`QUAD_READY mode=local camera=pose` and the 30-second `QUAD_MEDIA_SAMPLE`
records for SITL speed, encoded fps and valid pose counts. Stop with Ctrl+C
and check `QUAD_CHILDREN_REAPED`.

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
REDCON 2 and 3 reflect readiness during startup, degradation and shutdown.
Lifecycle messages appear in the notification tray and Session Log.

At REDCON 2, Office can connect to MAVLink in **View only**. The MAVLink dot
and telemetry panel report the browser peer's connection and heartbeat
status. At REDCON 1, Office also opens the camera and enables flight actions
as soon as the browser receives fresh telemetry and video.

Each connection starts in **View only**. With live camera and MAVLink telemetry,
select **Acquire control** to reserve the free lease. **Take off** selects
Guided mode, arms through the normal checks, and climbs to 2 m. Office shows
the controller, camera and telemetry status, mode, arm and landed state,
altitude, heading, and speed.

Hold the movement buttons or use `W`/`S` for forward and back, `A`/`D` for
left and right, `R`/`F` for climb and descent, and `Q`/`E` for yaw. Releasing
the inputs commands a hover. Use **Land** and check for **Landed** and
**Disarmed** in the telemetry. **Release control** returns to View only.

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
   no active simulator or observer VM. Confirm its two registered KVS channels.
2. Select REDCON 1. Record readiness and command outcomes across three cold
   starts. Startup is bounded to 90 seconds. Record the actual ready, stop
   and terminal timestamps.
3. Confirm camera and heartbeat, take control, take off to 2 m, translate,
   climb, yaw, hover, land and release control. Use a second viewer to check
   exclusive control. Inspect both streams in Agent Debug, and record relay
   media performance with the diagnostics page.
4. Verify a normal stop, stop during startup, flight deadline and readiness
   loss recovery. Check that the old session cannot regain authority and
   that restart allocates a new session with a fresh disarmed aircraft.
   Verify both MicroVMs terminate and the respective shadows clear their
   active IDs.
5. Check applicable cloud rig and existing device regressions. Retain the
   [prior acceptance and approved hardware skips](https://github.com/mparkachov/txing/issues/182)
   with the new evidence. Use the retirement procedure after acceptance.

Use these bounds for the permanent device checks.

| Area | Evidence |
| --- | --- |
| Startup and teardown | Three cold starts reach operational within 90 seconds. Healthy Stop from startup or operational reaches terminal state within 30 seconds. Abrupt termination withdraws readiness within 15 seconds of the last health report and the next successful repair pass records the outcome. |
| Flight | Take off to 2 m ± 0.5 m, translate at least 1 m on both horizontal axes, change altitude by at least 0.5 m, yaw at least 45°, and hover within 0.5 m horizontally and vertically over five seconds after settling. Verify landed and disarmed. |
| Media | With operator and observer joined, sustain 640 × 360 and at least 12 decoded fps in 95% of five-second windows for a full-duration session. Measure p95 pose-to-display below 800 ms and a SITL rate of 0.95–1.05× wall time over rolling 30-second windows. Include forced relay and late joins across the five-minute TURN and ten-minute signaling windows. |
| Authority loss | Confirm old writes fail and LAND begins within two seconds of server-side revocation. A silently disconnected browser loses its lease within five seconds of its last successful renewal. Check touchdown and disarm in a healthy simulator, and verify terminal cleanup at the session deadline. |
| Observer and restart | The agent receives both streams and has no write authority. Stop, expiry, crash and rapid restart leave no stale observer, writable peer or duplicate simulator. |

[Milestone 11](https://github.com/mparkachov/txing/milestone/11)
· [Prior verification](https://github.com/mparkachov/txing/issues/182)
