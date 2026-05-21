# Witness

Witness is the Go Sparkplug projection Lambda deployed by the base AWS stack.

## Responsibilities

- subscribe to Sparkplug MQTT through an IoT topic rule
- project Sparkplug topic identity and payload metrics into the `sparkplug` named shadow
- keep the AWS-side lifecycle read model separate from the live Sparkplug publisher

Witness is the only authority that writes the `sparkplug` named shadow for rig and unit things.

## Deploy

Deploy or update the release-built Lambda code:

```bash
just aws::deploy-lambdas latest
```

The `witness/` directory is a Go Lambda project and owns the active
Lambda source and tests. The primary deployment flow does not use a separate
witness stack or a witness-local CloudFormation template.

Apply infrastructure changes with the shared AWS stack:

```bash
just aws::deploy
```

`aws::deploy` does not build or upload witness code. The direct local Lambda
deploy recipe is disabled; use the release workflow and `aws::deploy-lambdas`
for production updates.

The deeper projection semantics are documented in:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)
