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

The cloud rig runtime Lambda is invoked once per minute by an EventBridge
Scheduler schedule while the cloud rig is `NBIRTH redcon=1`. It publishes the
cloud rig Sparkplug node as REDCON `1`, discovers registered `cloud-mcu`
devices, and sends SQS watch-link ticks based on each device's desired REDCON:
sleeping/default devices receive one immediate tick per minute, while REDCON `3`
devices keep ten ticks at offsets `0, 6, ..., 54` seconds for ECS task
reconciliation.

The same Lambda is also invoked by Sparkplug `NCMD.redcon` on
`spBv1.0/<town>/NCMD/<cloud-rig>`. `NCMD.redcon=4` disables the recurring
EventBridge Scheduler schedule and publishes `NBIRTH redcon=4`, leaving the rig
reachable/commandable without recurring Fleet Indexing, SQS tick batching,
shadow updates, or Sparkplug tick publications. `NCMD.redcon=1` enables the
schedule and runs the scheduler body once immediately so ticks resume without
waiting for the next minute.

The cloud MCU runtime Lambda is invoked by SQS ticks and Sparkplug `DCMD.redcon`.
`DCMD.redcon` stores desired REDCON `3` or `4` in the `power` named shadow and
queues one immediate SQS tick so command convergence does not wait for the next
minute schedule. SQS ticks reconcile the desired state by starting or stopping
one tagged Fargate task for the device. Ticks update named shadows and publish
device Sparkplug only when the rendered state or command feedback changes, so an
idle sleeping device does not produce recurring shadow writes or
witness-triggering Sparkplug data. Tasks are also started with a deterministic
ECS `startedBy` value derived from the thing name; every REDCON `3` tick lists
active tasks with that value and stops duplicates so only one active task is
associated with a device.

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

## Idle Counted Soak

For TASK-23.2, verify an already-born sleeping `cloud-mcu` device after the
updated CloudFormation stacks and Lambda artifacts are deployed:

1. Command the device to REDCON `4` and wait for the command feedback tick to
   converge.
2. Start a fixed observation window of at least 5 minutes with no further DCMD
   traffic for that device.
3. Confirm the cloud rig scheduler invokes once per minute and the sleeping
   device produces one cloud MCU SQS invocation per minute, not ten. With one
   sleeping device this is one `txing-cloud-mcu-lambda` invocation per minute;
   with N sleeping devices it is N invocations per minute.
4. Confirm the stable window has no recurring cloud MCU `UpdateThingShadow`
   calls for the device and no recurring device `DBIRTH` or `DDATA` publishes.
   The witness Lambda and `sparkplug` shadow projection should only move if a
   device Sparkplug message is actually published.
5. Ignore the cloud rig node `NBIRTH` refresh for this device count; that minute
   liveness publication is intentionally unchanged by this task.

This is the supported AWS-hosted software device type for cloud rigs. The
deprecated AWS-hosted cloud runtime package has been removed from the
repository; any remaining deployed legacy cloud runtime resources are manual
one-time account cleanup.
