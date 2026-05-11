# Witness

Witness is the Rust Sparkplug projection Lambda deployed by the base AWS stack.

## Responsibilities

- subscribe to Sparkplug MQTT through an IoT topic rule
- project Sparkplug topic identity and payload metrics into the `sparkplug` named shadow
- keep the AWS-side lifecycle read model separate from the live Sparkplug publisher

Witness is the only authority that writes the `sparkplug` named shadow for rig and unit things.

## Deploy

```bash
just aws::deploy
```

The `witness/` directory is a plain Cargo Lambda project and owns the active
Lambda source and tests. The primary deployment flow does not use a separate
witness stack or a witness-local CloudFormation template.

Update only the Lambda code after the base stack exists:

```bash
cd witness
cargo lambda build --release
cargo lambda deploy
```

The deeper projection semantics are documented in:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)
