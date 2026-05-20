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
devices, and sends ten SQS watch-link ticks per device at offsets `0, 6, ...,
54` seconds.

`txing-cloud-mcu-lambda` is invoked by SQS ticks and Sparkplug `DCMD.redcon`.
`DCMD.redcon` stores desired REDCON `3` or `4` in the `power` named shadow. The
next SQS tick reconciles the desired state by starting or stopping one tagged
Fargate task for the device.

## Deployment

Create or update the shared AWS stack and release Lambda artifacts:

```sh
just aws::deploy-lambdas latest
just aws::deploy
```

Register a device on a cloud rig:

```sh
just aws::deploy-device <cloud-rig-id> cloud-mcu cloud
```

This is a forward-only replacement for the old `time` cloud runtime. Existing
`time` things, old named shadows, and old deployed Lambda resources should be
removed manually after the new stack is deployed and verified.

Manual cleanup candidates include old `time-*` IoT things, their `sparkplug`,
`mcp`, and `time` named shadows, old `txing-time-lambda` functions/rules if they
exist outside the current stack, and any old per-device time stacks. Packaging
bucket cleanup still lives under `just aws::delete-packaging-buckets`.
