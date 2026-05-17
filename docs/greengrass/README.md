# Rig Greengrass Components

This guide describes the Raspberry Pi 5 rig runtime on AWS IoT Greengrass
Nucleus Lite. Greengrass is a rig implementation detail; the component binaries
and deploy tooling live under `rig/`.

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

`txing-rig-deploy [auto|raspi|cloud|all]` is the stable Greengrass cloud
deployment path on rigs. It runs from mise-installed release artifacts, uploads
immutable artifacts to the Greengrass artifacts bucket, creates Greengrass
component versions, and creates continuous deployments for the rig-type thing
groups. Raspi deployments include the Sparkplug manager and BLE connectivity;
cloud deployments include the Sparkplug manager and AWS retained MQTT
connectivity. Unit v1 components are intentionally excluded from the migrated
deployment set.

The checked-in recipe files are publishing templates. Production deploys do not
use host-local `ggl-cli deploy`, `rig/build/greengrass-local`, or
`/var/lib/greengrass/config.db` state. The old local Greengrass Lite deploy path
is retained only as `just rig::deploy-local <rig-id>` for debugging Greengrass
Lite itself.

The Rust Greengrass SDK build is Linux-only in this repo. Stable rigs use
prebuilt Linux assets; source-checkout development and admin builder deploys
must run from Linux. macOS development uses `just rig::start` with the local
Unix-socket broker instead.

Stable Greengrass Lite is delivered from the official upstream AWS GitHub
release. Use mise to install the upstream arm64 Debian package payload, then
perform host configuration manually:

```bash
/home/txing/.local/bin/mise where txing-greengrass-lite
/home/txing/.local/bin/mise exec -- txing-rig-deploy auto
```

Source-checkout Greengrass Lite builds are for development and local debugging:

```bash
sudo apt install -y cmake build-essential pkg-config python3-venv python3-dev python3-pip git curl ninja-build unzip default-jre libssl-dev libcurl4-openssl-dev libdbus-1-dev libglib2.0-dev libavahi-client-dev libgirepository1.0-dev libcairo2-dev libreadline-dev uuid-dev libzip-dev libyaml-dev libsystemd-dev libevent-dev liburiparser-dev cgroup-tools bluez pi-bluetooth avahi-utils
cmake --version
just rig::build
just rig::install-service <rig-id>
```

Run the package install before `just rig::build`; the native build invokes
`cmake` directly for the checked-in Greengrass Lite submodule and also builds
the Rust Sparkplug manager, BLE connectivity, and AWS connectivity binaries with
the Linux-only Greengrass SDK feature. It no longer builds a local Matter
controller.

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

Repository code does not install Greengrass Lite host files, call systemd,
create users, write `/etc/greengrass/config.yaml`, enable rig-type-specific host
dependencies, migrate old installs, or remove the old custom `rig.service`.
Existing Greengrass state must be removed as a manual privileged
host-maintenance step before configuring a reused host. The standard systemd
entrypoint is `greengrass-lite.target`.

After stable release updates on a rig host, run:

```bash
/home/txing/.local/bin/mise upgrade
/home/txing/.local/bin/mise exec -- txing-rig-deploy auto
```

From an admin builder with installed release artifacts, use an explicit target
when needed:

```bash
txing-rig-deploy raspi
txing-rig-deploy cloud
txing-rig-deploy all
```

`txing-rig-deploy` publishes all three installed Rust Greengrass component
binaries and requires them to have the same stable project SemVer. Git metadata
is exported for diagnostics by the components, but it is not used as the
Greengrass component version.

The first argument is the target rig type (`auto`, `raspi`, `cloud`, or `all`).
When a new Greengrass component version is required, bump the whole project
release version first. The stable deploy tool does not inspect a checkout;
source-checkout `just rig::deploy` still rejects dirty worktrees.

Weather and power things are discovered from the normal AWS registry assignment.
The rig-wide Sparkplug manager publishes v2 inventory using the registered AWS
Thing ID as the expected BLE advertised identity name.
`dev.txing.rig.BleConnectivity` treats fresh matching advertisements as REDCON 4
availability, maps devices by advertised name first with GAP/local name only as
a fallback, connects to matching devices when possible, and reports active
domain availability from GATT state/measurement reads. Incoming REDCON 1 or 2
commands are normalized to the physical BLE active level REDCON 3 for current
weather and power firmware.

Use `just rig::restart` to restart the Greengrass Lite systemd units without
deploying new code. Do not expect restart to pick up a new local build; restart
only re-runs the component version already deployed into Greengrass.

AWS prerequisites are in `shared/aws/template.yaml`: the stack creates the
Greengrass artifact bucket, token exchange IAM role, AWS IoT role alias, and
certificate policy permissions for `iot:AssumeRoleWithCertificate`. The base
stack configures AWS IoT fleet indexing through a CloudFormation custom resource
so thing connectivity status is available in `AWS_Things`. Use
`just aws::configure-indexing` only as an explicit repair or verification command.
