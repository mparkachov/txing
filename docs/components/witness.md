# Witness

Witness is the Sparkplug projection Lambda deployed by the base AWS stack.

## Responsibilities

- subscribe to Sparkplug MQTT through an IoT topic rule
- project Sparkplug topic identity and payload metrics into the `sparkplug` named shadow
- keep the AWS-side lifecycle read model separate from the live Sparkplug publisher

Witness is the only authority that writes the `sparkplug` named shadow for rig and unit things.

## Deploy

```bash
just aws::deploy
```

The `witness/` directory owns source and tests. The primary deployment flow does
not use a separate witness stack.

The deeper projection semantics are documented in:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)
