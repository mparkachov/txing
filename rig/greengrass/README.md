# Rig Greengrass Components

This directory contains recipe templates for the Raspberry Pi 5 rig runtime on
AWS IoT Greengrass Nucleus Lite. Greengrass is a rig implementation detail, so
the templates live under `rig/`.

Unit device process components:

- `dev.txing.device.unit.SparkplugManager`: AWS registry, shadows, Sparkplug, and
  per-device AWS IoT MQTT sessions.
- `dev.txing.device.unit.ConnectivityBle`: BLE adapter for MCU rendezvous and GATT
  wake/sleep control.

Weather device process components:

- `dev.txing.device.weather.SparkplugManager`: Sparkplug B lifecycle for weather
  things assigned to the raspi rig.
- `dev.txing.device.weather.MatterWatch`: observe-only Matter watcher. It idles
  until `WeatherThingName` and `MatterNodeId` are configured in deployment.

Matter support is additive to the existing BLE stack. A raspi rig can run the
unit BLE components and the weather Matter components together, but Matter over
Thread needs IP reachability to the Thread network through a Thread Border
Router. Raspberry Pi 5 hardware does not include an 802.15.4 Thread radio by
itself.

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

`just rig::deploy` is the local Greengrass Lite development path. For raspi rigs
it deploys both current `unit` and `weather` component families. It builds wheels
for generic `rig`, device runtime packages, and `aws`, uses `uv pip install
--target` to assemble a self-contained artifact Python tree for the target
platform, builds the weather C++20 Matter watcher, generates concrete local
recipes under `rig/build/greengrass-local`, and runs `ggl-cli deploy`. The
generated recipe/artifact tree is kept until the next deploy because Greengrass
Lite copies artifacts asynchronously after the CLI returns.
The checked-in recipe files are publishing templates; local deployment does not
use their placeholder S3 URIs.

Native Greengrass Lite is built and installed through:

```bash
sudo apt install -y cmake build-essential pkg-config python3-venv python3-dev python3-pip git curl ninja-build unzip default-jre libssl-dev libcurl4-openssl-dev libdbus-1-dev libglib2.0-dev libavahi-client-dev libgirepository1.0-dev libcairo2-dev libreadline-dev uuid-dev libzip-dev libsqlite3-dev libyaml-dev libsystemd-dev libevent-dev liburiparser-dev cgroup-tools bluez pi-bluetooth avahi-utils
cmake --version
just rig::build-native
just rig::build
just rig::install-service <rig-id>
just rig::deploy <rig-id>
```

Run the package install before `just rig::build-native`; the native build invokes
`cmake` directly. `build-native` also checks out Nordic's `sdk-connectedhomeip`
under `rig/connectedhomeip` at the NCS `v3.3.0` Matter revision and builds a
local `chip-tool` for the rig. The checkout and build output are ignored by git.

Use the local Matter controller with:

```bash
just rig::chip-tool --help
```

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

`deploy` depends on `rig::build`, so a separate build step is not
required for the normal edit/pull/deploy loop. The recipe generates a local
Greengrass component version from the current short Git SHA, for example
`0.6.0+g4e1261afdf2b`, adding a dirty-tree hash when local changes are present,
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

To activate the weather watcher during raspi deploy, pass the weather thing name
and manually commissioned Matter node id in the eighth and ninth positional
arguments:

```bash
just rig::deploy <rig-id> '' '' '' '' ble-main txing <weather-thing-name> <matter-node-id>
```

Leave those values empty to deploy the weather components in idle mode. The
Matter watcher uses the `chip-tool` built by `just rig::build-native` when it is
available. Pass a custom executable path as the tenth positional argument only if
you want to use a different Project CHIP tool:

```bash
just rig::deploy <rig-id> '' '' '' '' ble-main txing <weather-thing-name> <matter-node-id> /path/to/chip-tool
```

When weather is enabled with a Matter node id, `rig::deploy` checks that the
configured or locally built `chip-tool` exists before installing the Greengrass
component.

The Matter watcher stores its `chip-tool` controller fabric under the component
work directory, exposed to the process as `WEATHER_CHIP_TOOL_STORAGE_DIR`.
Commission the weather node with the same storage directory before expecting the
watcher to read attributes.

Use `just rig::restart` to restart the Greengrass Lite systemd units without
deploying new code. Do not expect restart to pick up a new local build; restart
only re-runs the component version already deployed into Greengrass.

AWS prerequisites are in `shared/aws/template.yaml`: the stack creates the
Greengrass artifact bucket, token exchange IAM role, AWS IoT role alias, and
certificate policy permissions for `iot:AssumeRoleWithCertificate`. The base
stack configures AWS IoT fleet indexing through a CloudFormation custom resource
so thing connectivity status is available in `AWS_Things`. Use
`just aws::configure-indexing` only as an explicit repair or verification command.
