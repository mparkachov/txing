# Rig Greengrass Components

This directory contains recipe templates for the Raspberry Pi 5 rig runtime on
AWS IoT Greengrass Nucleus Lite. Greengrass is a rig implementation detail, so
the templates live under `rig/`.

Components:

- `dev.txing.rig.SparkplugManager`: AWS registry, shadows, Sparkplug, and
  per-device AWS IoT MQTT sessions.
- `dev.txing.rig.ConnectivityBle`: BLE adapter for MCU rendezvous and GATT
  wake/sleep control.

Lifecycle boundary:

- `rig = Sparkplug edge node = Greengrass Lite core`.
- `dev.txing.rig.SparkplugManager` is the only txing component that publishes
  rig edge-node `NBIRTH` and `NDEATH`.
- Connectivity adapters never publish Sparkplug node lifecycle.
- Managed txing/unit things use device `DBIRTH` and `DDEATH`; the rig itself
  must not be represented as a Sparkplug device.
- Greengrass core/component status and AWS IoT MQTT lifecycle events are useful
  operational signals, but Sparkplug `NBIRTH` and `NDEATH` remain the
  authoritative txing rig lifecycle.

The recipes expect an offline artifact ZIP named `rig-greengrass.zip` with a
`wheels/` directory containing the built `rig`, `unit-rig`, `aws`, and third
party wheels for Linux `aarch64`. Replace the placeholder S3 URI in each recipe
when publishing the components.

Native Greengrass Lite is built and installed through:

```bash
sudo apt install -y cmake build-essential pkg-config libssl-dev libcurl4-openssl-dev uuid-dev libzip-dev libsqlite3-dev libyaml-dev libsystemd-dev libevent-dev liburiparser-dev cgroup-tools
cmake --version
just rig::build-native
just rig::build
just rig::install-service
```

Run the package install before `just rig::build-native`; the native build invokes
`cmake` directly.

Run `just aws::cert` before `just rig::install-service`. The install recipe
copies `config/certs/rig/rig.cert.pem` and `rig.private.key` into
`/var/lib/greengrass/credentials` and downloads Amazon Root CA 1.

`just rig::install-service` uses the upstream CMake install target and
Greengrass Lite `misc/run_nucleus` script; it does not create or rename txing
systemd units. The standard systemd entrypoint is `greengrass-lite.target`.

AWS prerequisites are in `shared/aws/template.yaml`: the stack creates the
Greengrass artifact bucket, token exchange IAM role, AWS IoT role alias, and
certificate policy permissions for `iot:AssumeRoleWithCertificate`. AWS IoT
fleet indexing must also be configured with `just aws::configure-indexing` so
thing connectivity status is available in `AWS_Things`.
