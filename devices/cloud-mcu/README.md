# Cloud MCU Device

`cloud-mcu` is a software-only txing device type for cloud rigs. Its watch link
is SQS, and its MCU behavior runs in AWS Lambda.

The runtime is split into two release-built Lambda functions:

```text
txing-cloud-rig-lambda
txing-cloud-mcu-lambda
```

`txing-cloud-rig-lambda` is invoked once per minute by EventBridge. It publishes
the cloud rig Sparkplug node as REDCON `1`, discovers registered `cloud-mcu`
devices, and sends one SQS batch per device with ten watch-link ticks at offsets
`0, 6, ..., 54` seconds.

`txing-cloud-mcu-lambda` is invoked by SQS ticks and Sparkplug `DCMD.redcon`.
`DCMD.redcon` stores desired REDCON `3` or `4` in the `power` named shadow. The
next SQS tick reconciles the desired state by starting or stopping one tagged
Fargate task for the device. Tasks are also started with a deterministic ECS
`startedBy` value derived from the thing name; every tick lists active tasks with
that value and stops duplicates so only one active task is associated with a
device.

## Deployment

Create or update the shared AWS stack and release Lambda artifacts:

```sh
just aws::publish-lambda latest
just aws::deploy
just aws::publish latest
```

Register a device on a cloud rig:

```sh
just aws::deploy-device <cloud-rig-id> cloud-mcu cloud
```

This is the supported AWS-hosted software device type for cloud rigs. The
deprecated AWS-hosted cloud runtime package has been removed from the
repository; any remaining deployed legacy cloud runtime resources are manual
one-time account cleanup.
