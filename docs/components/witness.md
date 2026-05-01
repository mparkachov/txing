# Witness

Witness is the standalone Sparkplug projection component.

## Responsibilities

- subscribe to Sparkplug MQTT through an IoT topic rule
- project Sparkplug topic identity and payload metrics into the `sparkplug` named shadow
- keep the AWS-side lifecycle read model separate from the live Sparkplug publisher

Witness is the only authority that writes the `sparkplug` named shadow for rig and unit things.

## Deploy

```bash
just witness::deploy
```

Default stack naming:

- witness stack: `${AWS_STACK_NAME}-witness`
- Lambda function: `${AWS_STACK_NAME}-witness`
- log group: `/aws/lambda/${AWS_STACK_NAME}-witness`

The deeper projection semantics are documented in:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)
