# time device

`time` is a software-only txing device type. Its device runtime is an AWS Lambda
invoked by EventBridge and AWS IoT MQTT topics. It is compatible with rigs whose
IoT registry `rigType` attribute is `aws`.

The Lambda stores its small active/sleep bookkeeping state in the `time` named
shadow for the device thing.

Rig enrollment and Greengrass deployment are not owned by this device package.
Configure the normal `config/aws.env` rig identity, for example:

```sh
TXING_RIG_NAME=aws
RIG_NAME=aws
TXING_RIG_TYPE=aws
SPARKPLUG_EDGE_NODE_ID=aws
```

Then use the normal rig path:

```sh
just aws::rig-deploy
just rig::install-service
just rig::deploy
```

Device enrollment is still device-specific. Set `TXING_DEVICE_TYPE=time` and
`TXING_DEVICE_NAME=clock`, then run `just aws::device-deploy`. Enrollment checks
the `time` manifest compatibility against the target rig's `rigType`.

The Lambda runtime is deployed separately with:

```sh
just time::deploy-lambda
```
