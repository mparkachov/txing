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
