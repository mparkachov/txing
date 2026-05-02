# Rig Greengrass Components

This directory contains recipe templates for the Raspberry Pi 5 rig runtime on
AWS IoT Greengrass Nucleus Lite. Greengrass is a rig implementation detail, so
the templates live under `rig/`.

Unit device process components:

- `dev.txing.device.unit.SparkplugManager`: AWS registry, shadows, Sparkplug, and
  per-device AWS IoT MQTT sessions.
- `dev.txing.device.unit.ConnectivityBle`: BLE adapter for MCU rendezvous and GATT
  wake/sleep control.

Lifecycle boundary:

- `rig = Sparkplug edge node = Greengrass Lite core`.
- `dev.txing.device.unit.SparkplugManager` is the only txing component that publishes
  rig edge-node `NBIRTH` and `NDEATH`.
- Connectivity adapters never publish Sparkplug node lifecycle.
- Managed txing/unit things use device `DBIRTH` and `DDEATH`; the rig itself
  must not be represented as a Sparkplug device.
- Greengrass core/component status and AWS IoT MQTT lifecycle events are useful
  operational signals, but Sparkplug `NBIRTH` and `NDEATH` remain the
  authoritative txing rig lifecycle.

`just rig::deploy` is the local Greengrass Lite development path. It
builds wheels for generic `rig`, `unit-rig`, and `aws`, uses `uv pip install --target` to
assemble a self-contained artifact Python tree for the target platform,
generates concrete local recipes under `rig/build/greengrass-local`, and runs
`ggl-cli deploy`. The generated recipe/artifact tree is kept until the next
deploy because Greengrass Lite copies artifacts asynchronously after the CLI
returns.
The checked-in recipe files are publishing templates; local deployment does not
use their placeholder S3 URIs.

Native Greengrass Lite is built and installed through:

```bash
sudo apt install -y cmake build-essential pkg-config python3-venv libssl-dev libcurl4-openssl-dev uuid-dev libzip-dev libsqlite3-dev libyaml-dev libsystemd-dev libevent-dev liburiparser-dev cgroup-tools
cmake --version
just rig::build-native
just rig::build
just rig::install-service
just rig::deploy
```

Run the package install before `just rig::build-native`; the native build invokes
`cmake` directly.

Run `just aws::cert` before `just rig::install-service`. The install recipe
copies `config/certs/rig/rig.cert.pem` and `rig.private.key` into
`/var/lib/greengrass/credentials`, downloads Amazon Root CA 1, resolves the rig
thing, AWS IoT endpoints, and Greengrass token exchange role alias from AWS, and
writes `/etc/greengrass/config.yaml`.

Use `just rig::check` to validate the certificate material in
`config/certs/rig/` before install or deployment. The check performs AWS IoT MQTT
mTLS and AWS IoT Credentials Provider role-alias probes with the local rig
certificate. It also validates rig identity consistency, the configured
registry `rigType`, and host services required by that rig type.

`just rig::install-service` uses the upstream CMake install target and
Greengrass Lite `misc/run_nucleus` script; it does not create or rename txing
systemd units, does not enable rig-type-specific host dependencies, and does not
remove the old custom `rig.service`. The standard systemd entrypoint is
`greengrass-lite.target`.

After code changes or `git pull`, run:

```bash
just rig::deploy
```

`deploy` depends on `rig::build`, so a separate build step is not
required for the normal edit/pull/deploy loop.

To force a new Greengrass component version from local artifacts:

```bash
TXING_RIG_COMPONENT_VERSION=0.5.1 just rig::deploy
```

Do not run `just rig::deploy component_version=0.5.1`; values after the recipe
name are positional recipe arguments.

Use `just rig::restart` to restart the Greengrass Lite systemd units without
deploying new code. Do not expect restart to pick up a new local build; restart
only re-runs the component version already deployed into Greengrass.

AWS prerequisites are in `shared/aws/template.yaml`: the stack creates the
Greengrass artifact bucket, token exchange IAM role, AWS IoT role alias, and
certificate policy permissions for `iot:AssumeRoleWithCertificate`. AWS IoT
fleet indexing must also be configured with `just aws::configure-indexing` so
thing connectivity status is available in `AWS_Things`.
