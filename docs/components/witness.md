# Witness

Witness is the Go Sparkplug projection Lambda deployed by the standalone
`witness/` stack.

## Responsibilities

- subscribe to Sparkplug MQTT through an IoT topic rule
- project Sparkplug topic identity and payload metrics into the `sparkplug` named shadow
- keep the AWS-side lifecycle read model separate from the live Sparkplug publisher
- provide the independent, delayed, stop-only
  [agent shutdown watch](../constraints/agent-watch.md)

Witness is the only authority that writes the `sparkplug` named shadow for rig and unit things.
It reads the controller-owned `agent` shadow without writing it. Successful
Sparkplug projection includes a bounded watch check; a one-minute rule also
runs the watch without device traffic. Configure the same dedicated agent image
name on both stacks. Off/expired assignments receive a two-minute repair grace;
the normal C++ controller remains responsible for prompt shutdown.

## Deploy

Create or update the witness Lambda stack:

```bash
just witness::deploy
```

To configure the independent watch, run the deployment manually with the
existing environment and dedicated image name:

```sh
just witness::deploy <environment-stack> <agent-image-name>
```

The first deployment defaults the image to `disabled`; later deployments that
omit it preserve the existing CloudFormation parameter. Publish a new shared
`lambda` release for witness source changes before enabling its schedule. See
the watch document for required controller artifacts and live acceptance.

Publish release-built runtime Lambda code after the GitHub release exists:

```bash
just release::publish lambda
```

`witness::deploy` creates the shared Lambda artifact bucket when needed and
seeds a placeholder `lambda/txing-witness-lambda/current/bootstrap.zip` object
before creating the function. The placeholder is only a bootstrap artifact for
CloudFormation; release code is still published from GitHub release assets.
`release::publish lambda` publishes already-built artifacts to all three
existing Go runtime Lambda functions together.

The deeper projection semantics are documented in:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)
