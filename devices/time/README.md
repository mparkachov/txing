# time device

`time` is a software-only txing device type. Its device runtime is an AWS Lambda
invoked by EventBridge and AWS IoT MQTT topics. It is compatible with rigs whose
IoT registry `rigType` attribute is `cloud`.

The Lambda stores its small active/sleep bookkeeping state in the `time` named
shadow for the device thing.

Rig enrollment and Greengrass deployment are not owned by this device package.
The shared AWS deployment syncs the hardcoded SSM type catalog at `/txing`, then
AWS IoT thing IDs identify concrete instances:

```sh
just aws::deploy
just aws::town-deploy town
just aws::rig-deploy <town-id> cloud aws
```

Then use the normal rig path:

```sh
just rig::install-service <rig-id>
just rig::deploy <rig-id>
```

Device enrollment is still device-specific:

```sh
just aws::device-deploy <rig-id> time clock
```

Enrollment checks the `/txing/town/cloud/time` compatibility record before
creating the device thing.

The Lambda runtime is deployed separately with:

```sh
just time::deploy-lambda <thing-id>
```
