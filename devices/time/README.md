# time device

`time` is a software-only txing device type. Its Rust device runtime is an AWS
Lambda invoked by EventBridge and AWS IoT MQTT topics. It is compatible with
rigs whose AWS IoT ThingType is `cloud`.

The Lambda stores its small active/sleep bookkeeping state in the `time` named
shadow for the device thing.

Rig enrollment and Greengrass deployment are not owned by this device package.
The shared AWS deployment creates the nested ThingType stacks and the SSM type
catalog at `/txing`, then AWS IoT thing IDs identify concrete instances:

```sh
just aws::deploy-lambdas latest
just aws::deploy
just aws::deploy-town town
just aws::deploy-rig <town-id> cloud aws
```

Then use the normal rig path:

```sh
just rig::install-service <rig-id>
just rig::deploy cloud
```

Device enrollment is still device-specific:

```sh
just aws::deploy-device <rig-id> time clock
```

Enrollment checks the `/txing/town/cloud/time/kind` compatibility leaf before
creating the device thing.

The time Lambda infrastructure is generic and owned by the shared `cloud-time`
type stack. Deploy or update the release-built Lambda code from the operator
machine:

```sh
just aws::deploy-lambdas latest
```

Deploy or update infrastructure with the shared AWS stack:

```sh
just aws::deploy
```

Existing per-device time Lambda stacks are legacy cleanup only.
