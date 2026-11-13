# Virtual quadcopter

The first milestone gate is [Lambda MicroVM runtime qualification](qualification/README.md).
The qualification workload runs ArduCopter SITL and two read-only WebRTC
streams. The [architecture plan](../../docs/virtual-quadcopter-architecture.md)
covers the device, Office controls, session lifecycle and agent integration.

## Enlistment

Deploy the shared AWS stack to register the `virtual-quad` type and publish
the corresponding [cloud rig Lambda release](../cloud-mcu/README.md#aws-deploy-and-runtime-publish).
Enlist the device on an existing cloud rig.

```sh
just aws::deploy-device <cloud-rig-id> virtual-quad virtual-quad
```

The enlist operation creates the Thing, the five named shadows and the
device's `-board-video` and `-mavlink` signaling channels. The
[manifest](manifest.toml) identifies the shadow contracts, with examples
in [fixtures](aws/fixtures/).

The next awake cloud rig census announces the device at REDCON 4 with
Sparkplug and simulation available. Office lists it under the assigned rig
and shows Start while the rig reports awake. Enlistment and the stopped
census use neither simulator nor observer compute. Session launch is tracked
in [#178](https://github.com/mparkachov/txing/issues/178).

## Session image

Run `just virtual-quad::microvm-package microvm-session` from the repository
root to build the ARM64 bundle for managed sessions. The supervisor claims its
assigned session before starting SITL or connecting the device's signaling
channels. The recipe prints the archive path to stdout.

In the Frankfurt environment, `just virtual-quad::deploy` prepares the
build role, logs, and session table and prints the CloudFormation outputs.
Run `just virtual-quad::publish-image <bundle-path>` to upload the archive
and submit the ARM64 MicroVM image build. The recipe looks up the image
name, artifact bucket, build role, log group and supported base version.
It returns the image ARN and version to inspect while the build runs.

Deploy the updated AWS release publisher and run
`just release::publish lambda <release>` to stage the controller bootstrap.
Once the image version is successful and active, run
`just virtual-quad::deploy <image-version>` to pin it and enable the
controller, device command rule and repair schedule. In Office, open the
device on an awake cloud rig and use Start or Stop in the device header.

## Live media

The onboard camera uses the current SITL truth pose to render a 640 × 360
view at 15 fps. During startup, REDCON 2 indicates that the worker has a
fresh SITL heartbeat and a MAVLink signaling master. Once the session is
operational, Office opens separate video and MAVLink peers as each capability
becomes available. Session changes and readiness expiry close those peers.

If a KVS master disconnects, Office withdraws the affected capability. The
controller gives the masters up to 30 seconds to reconnect while the worker
continues to report fresh SITL heartbeat and navigation. Missing worker
health or unhealthy SITL retains the 15-second cutoff.

To verify the pose camera and encoder in the local ARM64 image, run
`just virtual-quad::microvm-package microvm-session`, then run the image
without network access.

```sh
nerdctl.lima run --rm --platform linux/arm64 --network none \
  txing-virtual-quad-microvm-session:local local-camera
```

Check for `QUAD_READY mode=local camera=pose` and the following
`QUAD_MEDIA_SAMPLE` records. They report SITL speed, encoder output and
the count of valid truth-pose samples.

The local Office development page at `/virtual-quad-qualification.html`
records decoded frame counts, ICE candidate types and MAVLink frames in
five-second windows. For pose-to-display timing, use the session's
`QUAD_CAMERA_RTP_EPOCH` value as the RTP time base and a browser with a
synchronized clock that exposes RTP timestamps in video-frame callbacks.
Download the samples to retain the per-frame timing measurements.
The download also includes timestamped simulator positions, arm and mode
heartbeats, and landed-state changes for flight measurements.

## Flight in Office

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
