# Rig Greengrass Components

Rig Greengrass runtime, initial installation, deployment, health-check, and
cleanup instructions live in [components/rig.md](../components/rig.md).

The files under `rig/greengrass/` are publishing templates for txing `raspi`
rig Greengrass components. Production `raspi` rigs do not run host-local
`ggl-cli deploy`, do not use `rig/build/greengrass-local`, and do not depend on
`/var/lib/greengrass/config.db` state. Component versions are published from
the operator machine with:

```bash
just aws::publish-rig latest
```

The local deployment path is retained only for debugging txing components
against an already installed Greengrass Lite runtime:

```bash
just rig::deploy-local <rig-id>
```
