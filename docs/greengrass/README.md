# Rig Greengrass Components

Rig Greengrass runtime, initial installation, deployment, health-check, and
cleanup instructions live in [components/rig.md](../components/rig.md).

The files under `rig/greengrass/` are publishing templates for txing
Greengrass components. Production rigs do not run host-local
`ggl-cli deploy`, do not use `rig/build/greengrass-local`, and do not depend on
`/var/lib/greengrass/config.db` state. Txing component versions are published
from the operator machine with:

```bash
just rig::deploy-release latest all
```

The old local deployment path is retained only for debugging Greengrass Lite
itself:

```bash
just rig::deploy-local <rig-id>
```
