# Rig

The rig is the always-on coordinator and Sparkplug edge node. The current
`raspi` rig type runs a rig-wide Sparkplug manager plus transport-level BLE
connectivity for power and weather devices. The `cloud` rig type runs the
virtual `time` device connectivity adapter on Greengrass Lite without host
hardware.

## Current Responsibilities

- connect to AWS IoT Core over SigV4-authenticated MQTT over WebSockets
- publish Sparkplug node lifecycle for the rig edge node with `NBIRTH` and `NDEATH`
- publish Sparkplug device lifecycle for managed txing things with `DBIRTH`, `DDATA`, and `DDEATH`
- accept Sparkplug `DCMD.redcon`
- bridge REDCON commands to transport adapters over local Greengrass IPC
- derive device REDCON from adapter capability availability

Witness, not rig, writes the AWS-side `sparkplug` named shadow projection.
Hard invariant: `rig = Sparkplug edge node = Greengrass Lite core`. The rig
itself must never be represented by Sparkplug device `DBIRTH` or `DDEATH`.

## Greengrass Lite Split

The rig has a Greengrass-oriented component split:

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
- `dev.txing.rig.AwsConnectivity`
  - bridges the same v2 capability contract to retained AWS IoT topics for cloud devices
  - contains no time-specific REDCON or metric mapping; time mapping lives in the time runtime package
- future connectivity adapters such as `dev.txing.rig.LoRaConnectivity`
  - should implement the same v2 capability contract using their own transport
  - must not publish Sparkplug node lifecycle

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
- Greengrass core/device/component status is service observability only; it is not the txing lifecycle source of truth
- v2 capability state from connectivity adapters selects the highest REDCON level whose type-catalog rule is satisfied
- raspi rigs run BLE connectivity for `sparkplug`/`ble`/`power`; board-owned retained state is consumed by SparkplugManager for `board`/`mcp`/`video`
- board-owned retained state is gated by BLE power availability, so REDCON `4` / power-off evidence clears `board`, `mcp`, and `video` without waiting for retained state TTL expiry
- current BLE devices advertise with the AWS Thing ID from MCU NVE as the primary identity name

The current contract sources are:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- `rig/ble-connectivity` Rust BLE connectivity component

## Build And Run

Stable rig hosts install release artifacts with `mise`. They do not need a repo
checkout, Rust toolchain, CMake, or local compilation.

Normal stable update on a rig host:

```bash
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise upgrade
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-rig-deploy auto
```

For source-checkout development or admin builder work, `rig::build` requires the
Greengrass Lite native toolchain. On Raspberry Pi OS Lite/Trixie, install at
least `cmake`, `build-essential`, `pkg-config`, `libssl-dev`,
`libcurl4-openssl-dev`, `libdbus-1-dev`, `uuid-dev`, `libzip-dev`,
`libyaml-dev`, `libsystemd-dev`, `libevent-dev`, `liburiparser-dev`, and
`cgroup-tools`.

```bash
just rig::check <rig-id>
just rig::build
just rig::install-service <rig-id>
just rig::log <rig-id>
```

`just rig::check` validates AWS control-plane access plus certificate-backed
AWS IoT connectivity from `config/certs/rig/`. It also checks that the configured
rig identity is internally consistent, the AWS IoT rig thing has a supported
rig ThingType, and host services required by the selected rig type are installed,
enabled, and active.

Useful options:

- `just rig::status <rig-id>`
- `just rig::log <rig-id>`
- `txing-ble-connectivity --dry-run`

The BLE connectivity component also accepts `--no-ble` for local diagnostics,
which publishes offline capability state instead of touching the host BLE
adapter.

## Service Install

```bash
sudo env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-greengrass-lite install <rig-id>
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise exec -- txing-rig-deploy auto
sudo systemctl status --with-dependencies greengrass-lite.target
```

`txing-greengrass-lite install <rig-id>` installs the mise-provided Greengrass
Lite payload, writes `/etc/greengrass/config.yaml`, installs certificate
material, and starts the standard `greengrass-lite.target` through Greengrass
Lite's `misc/run_nucleus` script. It does not create or remove a custom
`rig.service`, does not migrate old installs, and does not enable
rig-type-specific host services. Existing Greengrass state must be removed
manually before running it. Rig behavior comes from Greengrass deployments
selected by the configured `RIG_TYPE`.

## Rig Type Host Requirements

`RIG_TYPE=raspi` requires the host Bluetooth service because the connectivity
component uses BLE rendezvous with the MCU. Install and enable it manually:

```bash
sudo apt install -y bluez
sudo systemctl enable --now bluetooth.service
```

`RIG_TYPE=cloud` has no extra host service dependency beyond Greengrass Lite.

Run `just rig::check <rig-id>` after configuring the host. It fails if a required
service for the configured rig type is missing, disabled, or inactive.

Use `txing-rig-deploy auto` on a stable rig host after `mise upgrade`. It
resolves the local rig type, uses the installed stable component binaries,
uploads immutable artifacts under `artifacts/<component>/<version>/`, creates
component versions from the stable project SemVer, and creates the AWS
Greengrass deployment for the matching rig-type thing group. Admin builders with
a source checkout can still use `just rig::deploy raspi`, `cloud`, or `all`.

The production install path does not run `ggl-cli deploy`, does not stage
artifacts under `rig/build/greengrass-local`, and does not depend on
`/var/lib/greengrass/config.db`. Use `just rig::restart` only when you want to
restart the existing Greengrass Lite systemd units without changing the deployed
component version.

The old local Greengrass Lite deploy path is available only as a debug escape
hatch:

```bash
just rig::deploy-local <rig-id>
```

Host setup details live in [installation.md](../installation.md). AWS bootstrap and registry steps live in [aws.md](../aws.md).
