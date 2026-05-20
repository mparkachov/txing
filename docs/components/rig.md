# Rig

The rig is the always-on coordinator and Sparkplug edge node. The current
`raspi` rig type runs a rig-wide Sparkplug manager plus transport-level BLE
connectivity for power and weather devices. The `cloud` rig type is AWS-hosted:
EventBridge runs `txing-cloud-rig-lambda` once per minute, SQS delayed messages
act as the watch link, and `txing-cloud-mcu-lambda` reconciles `cloud-mcu`
devices every six seconds.

## Current Responsibilities

- connect to AWS IoT Core over SigV4-authenticated MQTT over WebSockets
- publish Sparkplug node lifecycle for the rig edge node with `NBIRTH` and `NDEATH`
- publish Sparkplug device lifecycle for managed txing things with `DBIRTH`, `DDATA`, and `DDEATH`
- accept Sparkplug `DCMD.redcon`
- for `raspi`, bridge REDCON commands to transport adapters over local
  Greengrass IPC
- derive device REDCON from transport/runtime capability availability

Witness, not rig, writes the AWS-side `sparkplug` named shadow projection.
Hard invariant: `rig = Sparkplug edge node`. For `raspi` rigs that edge node is
the Greengrass Lite core running txing rig components. For `cloud` rigs that
edge node is the AWS-hosted `txing-cloud-rig-lambda` runtime. The rig itself
must never be represented by Sparkplug device `DBIRTH` or `DDEATH`.

## Raspi Greengrass Split

The `raspi` rig host has a Greengrass-oriented component split:

- `dev.txing.rig.SparkplugManager`
  - owns AWS registry discovery, type-catalog reads, REDCON derivation, and Sparkplug lifecycle
  - defines its direct AWS IoT MQTT connection as the rig edge-node `NBIRTH` condition
  - publishes explicit rig edge-node `NDEATH` on graceful shutdown and configures `NDEATH` as MQTT Last Will
  - uses direct per-device AWS IoT MQTT sessions so `DBIRTH` and `DDEATH` are coupled to each device session lifecycle
- `dev.txing.rig.BleConnectivity`
  - owns BLE scanning, multi-device connected-idle GATT sessions, REDCON writes, and power/weather state reads
  - communicates with the manager only through local Greengrass pub/sub topics under `dev/txing/rig/v2/#`
  - publishes BLE-owned named shadow updates through Greengrass IPC `PublishToIoTCore`
  - owns top-level reported fields in the `ble` shadow plus domain shadows such as `power` and `weather`
  - never publishes Sparkplug node lifecycle
- future connectivity adapters such as `dev.txing.rig.LoRaConnectivity`
  - should implement the same v2 capability contract using their own transport
  - must not publish Sparkplug node lifecycle

The `cloud` rig runtime is not a Greengrass component split. Its active runtime
lives in `devices/cloud-mcu`: EventBridge invokes `txing-cloud-rig-lambda`, SQS
acts as the watch link, and `txing-cloud-mcu-lambda` reconciles `cloud-mcu`
devices.

## BLE REDCON Architecture

REDCON is the common lifecycle contract for txing BLE devices. The shared rig
BLE scanner stays device-agnostic and internal to
`dev.txing.rig.BleConnectivity`: it observes address, advertised identity name,
GAP/local name, RSSI, and service UUIDs, then routes matching devices to
protocol handlers. The advertised identity name is the primary Thing mapping
signal; GAP/local name is only a fallback. New device types should not add a
separate BLE manager or scanner only because they expose additional
characteristics.

Current assumption: REDCON GATT v2 uses one common UUID set for the base
lifecycle contract across BLE device types, with one measurement characteristic
per data capability.

```text
redcon service      f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100
redcon command      f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100  <version:u8=2, redcon:u8>
redcon state        f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100  <version:u8=2, redcon:u8>
power measurement   f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100  <version:u8=2, battery_mv:u16>
weather measurement f6b4b004-7b32-4d2d-9f4b-4ff0a2b8f100  <version:u8=2, temperature_centi:i32, pressure_pa:u32, humidity_centi:u16>
```

- the REDCON state characteristic is only the common observable lifecycle
  surface
- the REDCON command characteristic is present for device types that accept
  lifecycle commands; read-only devices may omit it and still report REDCON
  state
- data-producing capabilities are layered on top as separate measurement
  characteristics; multibyte fields are little-endian
- firmware owns measurement cadence: REDCON `3` every 10 seconds and REDCON `4`
  every 60 seconds
- a new service UUID set is reserved for a breaking change to the base REDCON
  contract or for a deliberate discovery-level distinction of a fundamentally
  different BLE contract; it is not needed for normal telemetry additions or
  configuration differences

Rig implementation keeps one transport-level BLE connectivity component with one
scanner, reusable REDCON client/parser behavior, and per-device-type named
shadow mapping inside that component. For example, `power` is REDCON plus a
`power` shadow battery reading while `weather` is REDCON plus a `weather` shadow
with weather measurements. Sparkplug lifecycle stays in
`dev.txing.rig.SparkplugManager` and carries only `redcon`, `capability.*`, and
current command-result feedback.

If a future REDCON version needs different UUIDs during a migration, the shared
BLE scanner should still remain common. The rig can add a REDCON profile
registry or client selection layer above discovery instead of duplicating BLE
management.

## Current Runtime Model

- managed devices come from AWS IoT Fleet Indexing with `attributes.rigId=<TXING_RIG_ID>`
- startup reads each device `DescribeThing` result, its ThingType, and the SSM type catalog
- Sparkplug lifecycle state is published only on MQTT; the AWS read model is witness-owned
- for `raspi`, Greengrass core/device/component status is service observability
  only; it is not the txing lifecycle source of truth
- v2 capability state from connectivity adapters, or cloud MCU SQS ticks,
  selects the highest REDCON level whose type-catalog rule is satisfied
- raspi rigs run BLE connectivity for `sparkplug`/`ble`/`power`; board-owned retained state is consumed by SparkplugManager for `board`/`mcp`/`video`
- board-owned retained state is gated by BLE power availability, so REDCON `4`
  / power-off evidence clears `board`, `mcp`, and `video` without waiting for
  retained state TTL expiry; after the next wake, fresh board-owned state must
  arrive before those capabilities become available again
- current BLE devices advertise with the AWS Thing ID from MCU NVE as the primary identity name

The current contract sources are:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- `rig/ble-connectivity` Rust BLE connectivity component

## Raspi Runtime

Production `raspi` rig hosts run the official AWS Greengrass Lite Debian
package plus txing Greengrass components delivered by cloud deployments. A
production `raspi` rig does not need a repo checkout, mise, AWS CLI, AWS access
keys, Rust toolchain, CMake, or local compilation. The rig stores only
Greengrass certificate material and the Greengrass Lite config fragment.

Production `raspi` setup is intentionally split:

1. The operator creates AWS resources, the rig thing, certificate material, and
   `config/certs/rig/greengrass-lite.yaml`.
2. The rig host installs the upstream Greengrass Lite Debian package and copies
   the generated certificate/config files into the Greengrass locations.
3. The operator publishes txing release artifacts to Greengrass with
   `just rig::deploy-release latest raspi`.
4. Greengrass Lite pulls and runs the deployed components.

Repository code does not install host files, write system directories, create
users, change ownership, call systemd, migrate old installs, remove old
services, or enable rig-type-specific host services. Those are manual privileged
host-maintenance steps.

## Raspi Initial Install

Before configuring a `raspi` rig host, the operator-side AWS setup must already
have:

- the base AWS stack and type catalog from `just aws::deploy`
- a town thing from `just aws::deploy-town town`
- a rig thing from `just aws::deploy-rig <town-id> raspi server`
- a completed GitHub release for the txing component version to deploy

On the operator machine, generate the rig certificate and Greengrass Lite config
from a txing checkout:

```bash
just aws::cert <rig-id>
```

If certificate material already exists and only the Greengrass Lite config is
missing or stale, regenerate just the config:

```bash
just aws::greengrass-config <rig-id>
```

Transfer these files from `config/certs/rig/` to the rig with your normal admin
workflow:

```text
rig.cert.pem
rig.private.key
AmazonRootCA1.pem
greengrass-lite.yaml
```

`greengrass-lite.yaml` already contains the rig thing name, AWS region, IoT data
endpoint, IoT credential provider endpoint, Greengrass token exchange role
alias, and `runWithDefault.posixUser: gg_component:gg_component`.

On the rig, use a privileged root shell for the remaining host configuration.
Install common runtime packages:

```bash
apt update
apt full-upgrade -y
apt install -y \
  curl ca-certificates unzip \
  libssl3 libcurl4 libdbus-1-3 libyaml-0-2 libsystemd0 \
  libevent-2.1-7 liburiparser1 cgroup-tools
```

If Greengrass Lite reports a missing `libzip.so.*`, install the matching
runtime package from the rig OS:

```bash
apt-cache search '^libzip[0-9]'
apt install -y <matching-libzip-package>
```

Install the upstream arm64 Greengrass Lite Debian package. Do not run
`install-greengrass-lite.sh`; txing uses the generated config fragment.

```bash
GGL_VERSION="2.5.1"
GGL_ZIP="/tmp/aws-greengrass-lite-deb-arm64.zip"
GGL_UNPACK="/tmp/aws-greengrass-lite"

curl -fL -o "$GGL_ZIP" "https://github.com/aws-greengrass/aws-greengrass-lite/releases/download/v$GGL_VERSION/aws-greengrass-lite-deb-arm64.zip"
rm -rf "$GGL_UNPACK"
install -d -m 755 "$GGL_UNPACK"
unzip -q "$GGL_ZIP" -d "$GGL_UNPACK"
apt install -y "$GGL_UNPACK/aws-greengrass-lite-$GGL_VERSION-Linux.deb"
rm -rf "$GGL_UNPACK" "$GGL_ZIP"
id ggcore >/dev/null
id gg_component >/dev/null
```

The package creates `ggcore` for Greengrass Lite core services and
`gg_component` for normal component runtime processes.

Install the generated rig certificate material and config:

```bash
RIG_CERT_PEM="./rig.cert.pem"
RIG_PRIVATE_KEY="./rig.private.key"
RIG_ROOT_CA="./AmazonRootCA1.pem"
GGL_CONFIG="./greengrass-lite.yaml"

install -d -o ggcore -g ggcore -m 700 /var/lib/greengrass/credentials
install -o ggcore -g ggcore -m 600 "$RIG_CERT_PEM" /var/lib/greengrass/credentials/rig.cert.pem
install -o ggcore -g ggcore -m 600 "$RIG_PRIVATE_KEY" /var/lib/greengrass/credentials/rig.private.key
install -o ggcore -g ggcore -m 644 "$RIG_ROOT_CA" /var/lib/greengrass/credentials/AmazonRootCA1.pem

install -d -m 755 /etc/greengrass/config.d
install -m 644 "$GGL_CONFIG" /etc/greengrass/config.d/greengrass-lite.yaml

chown -R ggcore:ggcore /var/lib/greengrass
systemctl daemon-reload
systemctl enable --now greengrass-lite.target
```

For `RIG_TYPE=raspi`, also install and enable Bluetooth support, then add the
component runtime user to the OS `bluetooth` group:

```bash
apt install -y bluez pi-bluetooth
systemctl enable --now bluetooth.service
getent group bluetooth
usermod -aG bluetooth gg_component
systemctl restart bluetooth.service
systemctl restart greengrass-lite.target
```

`cloud` rigs do not have a host install path. Deploy the AWS stack and Lambda
artifacts, register a `cloud` rig thing, and manage `cloud-mcu` devices through
the AWS-hosted runtime documented in `devices/cloud-mcu/README.md`.

## Deploy And Update

The `raspi` rig host does not run AWS CLI, GitHub CLI, mise, or deployment
scripts. Publish txing component versions from the operator machine after the
`Txing Release` workflow finishes:

```bash
gh auth status
just rig::deploy-release latest raspi
```

`rig::deploy-release` relies on native AWS CLI configuration plus an explicit
`TXING_AWS_STACK` in the operator environment; it fails before deployment if the
stack name is unset. The command downloads the GitHub release assets with `gh`,
uploads the Linux component binaries to the Greengrass artifact bucket, creates
Greengrass component versions from the project SemVer, and creates continuous
deployments for the `raspi` rig-type thing group. The Linux component binaries
are not executed on the operator Mac.

Use an explicit target when needed:

```bash
just rig::deploy-release latest raspi
```

Normal update:

1. Bump and push the project version files.
2. Run the `Txing Release` workflow on GitHub.
3. Run `just rig::deploy-release latest raspi` from the operator machine.

Greengrass Lite itself is installed as an upstream Debian package, not as a
txing release artifact or mise tool. Upgrade it manually only when AWS publishes
a newer upstream Greengrass Lite version you want to adopt.

The production install path does not run host-local `ggl-cli deploy`, does not
stage artifacts under `rig/build/greengrass-local`, and does not depend on
`/var/lib/greengrass/config.db`. The local txing component deployment path is
available only as a debug escape hatch against an already installed Greengrass
Lite runtime:

```bash
just rig::deploy-local <rig-id>
```

## Health Checks

Run these read-only checks on the rig as `ggcore` where permissions allow:

```bash
systemctl is-active greengrass-lite.target
systemctl --no-pager --full status greengrass-lite.target
systemctl is-active \
  ggl.core.ggconfigd.service \
  ggl.core.iotcored.service \
  ggl.core.tesd.service \
  ggl.aws.greengrass.TokenExchangeService.service \
  ggl.core.ggdeploymentd.service \
  ggl.core.gg-fleet-statusd.service

journalctl --no-pager -n 200 \
  -u ggl.core.iotcored.service \
  -u ggl.core.tesd.service \
  -u ggl.aws.greengrass.TokenExchangeService.service \
  -u ggl.core.ggdeploymentd.service \
  -u ggl.core.gg-fleet-statusd.service
```

Check installed config and certificate material:

```bash
test -r /etc/greengrass/config.d/greengrass-lite.yaml && sed -n '1,160p' /etc/greengrass/config.d/greengrass-lite.yaml
test -r /var/lib/greengrass/credentials/rig.cert.pem
test -r /var/lib/greengrass/credentials/rig.private.key
test -r /var/lib/greengrass/credentials/AmazonRootCA1.pem
openssl x509 -in /var/lib/greengrass/credentials/rig.cert.pem -noout -subject -issuer -enddate
```

`ggl-cli` in Greengrass Lite 2.5.1 has local deployment commands, but no
production `status` or AWS connectivity check. Prefer systemd status and
service logs for on-rig diagnostics.

## Manual Old Install Removal

Cleanup of old rigs is manual and intentionally not automated. From a privileged
root shell on the rig:

```bash
systemctl stop ggl.dev.txing.rig.SparkplugManager.service ggl.dev.txing.rig.BleConnectivity.service ggl.dev.txing.rig.AwsConnectivity.service greengrass-lite.target || true
systemctl disable greengrass-lite.target || true
rm -rf /etc/greengrass /var/lib/greengrass /run/greengrass
rm -f /etc/tmpfiles.d/txing-greengrass-lite.conf
systemctl daemon-reload
systemctl reset-failed
```

## Source Development

Source-checkout rig builds are for txing component development and local
debugging against an already installed upstream Greengrass Lite runtime. They
must run on Linux because the Rust Greengrass SDK build is Linux-only in this
repo. macOS development uses `just rig::start` with the local Unix-socket
broker instead.

On Raspberry Pi OS Lite/Trixie, install the upstream Greengrass Lite Debian
package first, then install the native prerequisites required by the txing
component builds: `build-essential`, `pkg-config`, `libssl-dev`,
`libdbus-1-dev`, `libzip-dev`, `libyaml-dev`, `libsystemd-dev`,
`libevent-dev`, `liburiparser-dev`, `cgroup-tools`, `bluez`, and
`pi-bluetooth`.

```bash
just rig::build
just rig::deploy-local <rig-id>
```

`just rig::check <rig-id>` is a source-checkout diagnostic for Linux hosts with
the relevant services available. It validates AWS control-plane access,
certificate-backed AWS IoT connectivity from `config/certs/rig/`, rig identity
consistency, registered rig ThingType, and selected host service prerequisites.

The BLE connectivity component also accepts `--no-ble` for local diagnostics,
which publishes offline capability state instead of touching the host BLE
adapter.

AWS bootstrap and registry steps live in [aws.md](../aws.md). Board host setup
lives in [board.md](./board.md).
