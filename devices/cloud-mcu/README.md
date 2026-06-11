# Cloud MCU Device

`cloud-mcu` is a software-only txing device type for cloud rigs. Its watch link
is SQS, and its MCU behavior runs in AWS Lambda.

The runtime is split into two release-built Lambda artifacts. Deployed function
names are prefixed with the environment stack name, for example
`town-cloud-rig`:

```text
txing-cloud-rig-lambda
txing-cloud-mcu-lambda
```

The cloud rig runtime Lambda is invoked once per minute by EventBridge while the
cloud rig is `NBIRTH redcon=1`. It publishes the cloud rig Sparkplug node as
REDCON `1`, discovers registered `cloud-mcu` devices, and sends one SQS batch
per device with ten watch-link ticks at offsets `0, 6, ..., 54` seconds.

The same Lambda is also invoked by Sparkplug `NCMD.redcon` on
`spBv1.0/<town>/NCMD/<cloud-rig>`. `NCMD.redcon=4` disables the recurring
EventBridge schedule and publishes `NBIRTH redcon=4`, leaving the rig
reachable/commandable without recurring Fleet Indexing, SQS tick batching,
shadow updates, or Sparkplug tick publications. `NCMD.redcon=1` enables the
schedule and runs the scheduler body once immediately so ticks resume without
waiting for the next minute.

The cloud MCU runtime Lambda is invoked by SQS ticks and Sparkplug `DCMD.redcon`.
`DCMD.redcon` stores desired REDCON `3` or `4` in the `power` named shadow. The
next SQS tick reconciles the desired state by starting or stopping one tagged
Fargate task for the device. Tasks are also started with a deterministic ECS
`startedBy` value derived from the thing name; every tick lists active tasks with
that value and stops duplicates so only one active task is associated with a
device.

## AWS Deploy And Runtime Publish

Create or update the CloudFormation-managed AWS infrastructure, then publish
the already-built runtime Lambda artifacts:

```sh
just aws::deploy
just release::publish lambda
```

The cloud MCU deploy step called by `just aws::deploy` owns all cloud
MCU-specific AWS infrastructure: the `cloud-mcu` type catalog entry, SQS tick
queues, IPv6-only ECS task network, placeholder task definition, and the two
runtime Lambda stacks. `just release::publish lambda` updates the existing
runtime Lambda functions from the `lambda-v*` release stream. The base AWS stack
only creates the shared `cloud` rig type and common txing infrastructure.
The cloud MCU stack publishes queue and runtime values under `/txing/stack/...`;
the cloud rig stack reads those parameters instead of reading CloudFormation
outputs from the cloud MCU stack.

Register a device on a cloud rig:

```sh
just aws::deploy-device <cloud-rig-id> cloud-mcu cloud
```

This is the supported AWS-hosted software device type for cloud rigs. The
deprecated AWS-hosted cloud runtime package has been removed from the
repository; any remaining deployed legacy cloud runtime resources are manual
one-time account cleanup.
