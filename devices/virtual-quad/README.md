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
