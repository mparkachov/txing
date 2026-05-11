# Rig Greengrass Components

This directory contains recipe templates for the Raspberry Pi 5 rig runtime on
AWS IoT Greengrass Nucleus Lite. Greengrass is a rig implementation detail, so
the templates live under `rig/`.

Rig-wide components:

- `dev.txing.rig.SparkplugManager`: Rust Sparkplug lifecycle manager for the rig
  edge node and all managed device sessions.
- `dev.txing.rig.BleConnectivity`: Rust transport-level BLE connectivity
  adapter for current raspi power and weather devices. It owns BLE scanning,
  connection scheduling, GATT command/state exchange, and publishes v2
  capability state/results.
- `dev.txing.rig.AwsConnectivity`: Rust transport-level AWS retained MQTT
  connectivity adapter for cloud devices. It owns retained v2 capability
  command/state/result forwarding and publishes local v2 capability messages.

Weather devices use the Raspberry Pi 5 built-in BLE controller. The weather rig
path does not require Matter, Thread, `chip-tool`, a Thread border router, or a
separate radio dongle.

Lifecycle boundary:

- `rig = Sparkplug edge node = Greengrass Lite core`.
- `dev.txing.rig.SparkplugManager` is the only txing component that publishes
  rig edge-node `NBIRTH` and `NDEATH`.
- Connectivity adapters never publish Sparkplug node lifecycle.
- Managed txing things use device `DBIRTH` and `DDEATH`; the rig itself
  must not be represented as a Sparkplug device.
- Greengrass core/component status and AWS IoT MQTT lifecycle events are useful
  operational signals, but Sparkplug `NBIRTH` and `NDEATH` remain the
  authoritative txing rig lifecycle.

`just rig::deploy` is the local Greengrass Lite development path. Raspi rigs
deploy the Rust rig-wide Sparkplug manager and the Rust BLE connectivity adapter.
Cloud rigs deploy the Rust rig-wide Sparkplug manager and the Rust AWS
connectivity adapter. Unit v1 components are intentionally excluded from the
migrated deployment set. The recipe builds the Rust manager binary and the
selected Rust connectivity binary. It assembles
self-contained artifacts, generates concrete local recipes under
`rig/build/greengrass-local`, and runs `ggl-cli deploy`. The generated
recipe/artifact tree is kept until the next deploy because Greengrass Lite copies
artifacts asynchronously after the CLI returns.
The checked-in recipe files are publishing templates; local deployment does not
use their placeholder S3 URIs.
The Rust Greengrass SDK build is Linux-only in this repo, so run
`just rig::deploy` on the Greengrass rig host rather than packaging the component
from macOS.

Native Greengrass Lite is built and installed through:

```bash
sudo apt install -y cmake build-essential pkg-config python3-venv python3-dev python3-pip git curl ninja-build unzip default-jre libssl-dev libcurl4-openssl-dev libdbus-1-dev libglib2.0-dev libavahi-client-dev libgirepository1.0-dev libcairo2-dev libreadline-dev uuid-dev libzip-dev libsqlite3-dev libyaml-dev libsystemd-dev libevent-dev liburiparser-dev cgroup-tools bluez pi-bluetooth avahi-utils
cmake --version
just rig::build
just rig::install-service <rig-id>
just rig::deploy <rig-id>
```

Run the package install before `just rig::build`; the native build invokes
`cmake` directly for Greengrass Lite and also builds the Rust Sparkplug manager,
BLE connectivity, and AWS connectivity binaries with the Linux-only Greengrass
SDK feature. It no longer builds a local Matter controller.

Run `just aws::cert <rig-id>` before `just rig::install-service <rig-id>`. The install recipe
copies `config/certs/rig/rig.cert.pem` and `rig.private.key` into
`/var/lib/greengrass/credentials`, downloads Amazon Root CA 1, resolves the rig
thing, AWS IoT endpoints, and Greengrass token exchange role alias from AWS, and
writes `/etc/greengrass/config.yaml`.

Use `just rig::check <rig-id>` to validate the certificate material in
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
just rig::deploy <rig-id>
```

`deploy` builds and stages the selected Rust Greengrass components, so a
separate build step is not required for the normal edit/pull/deploy loop. The
recipe generates a local
Greengrass component version from the current short Git SHA, for example
`0.8.0+g4e1261afdf2b`, adding a dirty-tree hash when local changes are present,
so checked-out code is deployed without manually changing version numbers.
Generated versions intentionally avoid `-` because Greengrass Lite's local
recipe filename scanner splits recipe names on the last hyphen.

Manual component version pinning is intentionally outside the normal workflow.
If needed while debugging Greengrass artifact caching, pass the internal fifth
positional argument:

```bash
just rig::deploy <rig-id> '' '' '' 0.5.1
```

Do not run `just rig::deploy component_version=0.5.1`; values after the recipe
name are positional recipe arguments. Normal deploys should leave the internal
component version empty.

Weather and power things are discovered from the normal AWS registry assignment.
The rig-wide Sparkplug manager publishes v2 inventory using the registered AWS
Thing ID as the expected BLE local name. `dev.txing.rig.BleConnectivity` treats
fresh matching advertisements as REDCON 4 availability, connects to matching
devices when possible, and reports active domain availability from GATT
state/measurement reads. Incoming REDCON 1 or 2 commands are normalized to the
physical BLE active level REDCON 3 for current weather and power firmware.

Use `just rig::restart` to restart the Greengrass Lite systemd units without
deploying new code. Do not expect restart to pick up a new local build; restart
only re-runs the component version already deployed into Greengrass.

AWS prerequisites are in `shared/aws/template.yaml`: the stack creates the
Greengrass artifact bucket, token exchange IAM role, AWS IoT role alias, and
certificate policy permissions for `iot:AssumeRoleWithCertificate`. The base
stack configures AWS IoT fleet indexing through a CloudFormation custom resource
so thing connectivity status is available in `AWS_Things`. Use
`just aws::configure-indexing` only as an explicit repair or verification command.
