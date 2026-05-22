# Witness

Witness is the Go Sparkplug projection Lambda deployed by the standalone
`witness/` stack.

## Responsibilities

- subscribe to Sparkplug MQTT through an IoT topic rule
- project Sparkplug topic identity and payload metrics into the `sparkplug` named shadow
- keep the AWS-side lifecycle read model separate from the live Sparkplug publisher

Witness is the only authority that writes the `sparkplug` named shadow for rig and unit things.

## Deploy

Create or update the witness Lambda stack:

```bash
just witness::deploy
```

Publish release-built witness code after the GitHub release exists:

```bash
just witness::publish latest
```

`witness::deploy` creates the shared Lambda artifact bucket when needed and
seeds a placeholder `lambda/txing-witness-lambda/current/bootstrap.zip` object
before creating the function. The placeholder is only a bootstrap artifact for
CloudFormation; release code is still published from GitHub release assets.

The deeper projection semantics are documented in:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)
