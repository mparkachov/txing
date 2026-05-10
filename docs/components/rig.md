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
`dev.txing.rig.BleConnectivity`: it observes address, local name, RSSI, and
service UUIDs, then routes matching devices to protocol handlers. New device
types should not add a separate BLE manager or scanner only because they expose
additional characteristics.

Current assumption: REDCON GATT v1 uses one common UUID set for the base
lifecycle contract across BLE device types.

```text
redcon service  f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100
redcon command  f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100
redcon state    f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100
```

- the REDCON state characteristic is the common observable lifecycle and battery
  surface
- the REDCON command characteristic is present for device types that accept
  lifecycle commands; read-only devices may omit it and still report REDCON
  state
- device-specific functionality should be layered on top of REDCON as extra
  characteristics or extra services
- weather telemetry can use an additional measurement characteristic, currently
  assumed to be `f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100`, while keeping the same
  REDCON service, command, and state UUIDs
- a new service UUID set is reserved for a breaking change to the base REDCON
  contract or for a deliberate discovery-level distinction of a fundamentally
  different BLE contract; it is not needed for normal telemetry additions or
  configuration differences

Rig implementation keeps one transport-level BLE connectivity component with one
scanner, reusable REDCON client/parser behavior, and per-device-type metric
mapping inside that component. For example, `power` is REDCON-only while
`weather` is REDCON plus weather measurements. Sparkplug lifecycle stays in
`dev.txing.rig.SparkplugManager`.

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
- current raspi BLE devices advertise with the AWS Thing ID as local name

The current contract sources are:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- `rig/ble-connectivity` Rust BLE connectivity component

## Build And Run

`rig::build-native` requires the Greengrass Lite native toolchain on the rig
host. On Raspberry Pi OS Lite/Trixie, install at least `cmake`,
`build-essential`, `pkg-config`, `libssl-dev`, `libcurl4-openssl-dev`,
`libdbus-1-dev`, `uuid-dev`, `libzip-dev`, `libsqlite3-dev`,
`libyaml-dev`, `libsystemd-dev`, `libevent-dev`, `liburiparser-dev`, and
`cgroup-tools`.

```bash
just rig::check <rig-id>
just rig::build-native
just rig::build
just rig::run
just rig::debug
```

`just rig::check` validates AWS control-plane access plus certificate-backed
AWS IoT connectivity from `config/certs/rig/`. It also checks that the configured
rig identity is internally consistent, the AWS IoT rig thing has a supported
rig ThingType, and host services required by the selected rig type are installed,
enabled, and active.

Useful options:

- `just rig::wake`
- `just rig::sleep`
- `txing-ble-connectivity --dry-run`

The BLE connectivity component also accepts `--no-ble` for local diagnostics,
which publishes offline capability state instead of touching the host BLE
adapter.

## Service Install

```bash
just rig::build-native
just rig::build
just rig::install-service <rig-id>
just rig::deploy <rig-id>
sudo systemctl status --with-dependencies greengrass-lite.target
```

`rig::build-native` builds Greengrass Lite with `GG_LOG_LEVEL=INFO` so the
standard Greengrass daemons do not flood journald with debug traces.

The install target no longer creates or removes a custom `rig.service`, and it
does not enable rig-type-specific host services. It resolves the configured rig
thing and Greengrass token exchange settings from AWS, writes
`/etc/greengrass/config.yaml`, installs the native Greengrass Lite build using
the upstream CMake install target, and starts the standard
`greengrass-lite.target` through Greengrass Lite's `misc/run_nucleus` script.
Rig behavior comes from Greengrass deployments selected by the configured
`RIG_TYPE`.

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

Use `just rig::deploy <rig-id>` after changing or pulling rig code; it depends
on `just rig::build`, generates a local component version from the current short
Git SHA, and then stages a new local component artifact under
`rig/build/greengrass-local`. That staging directory is intentionally kept until
the next deploy because Greengrass Lite copies artifacts asynchronously. Use
`just rig::restart` only when you want to restart the existing Greengrass Lite
systemd units without changing the deployed component version.

For local redeploys that must force a specific Greengrass component version,
pass the internal fifth positional argument:

```bash
just rig::deploy <rig-id> '' '' '' 0.5.1
```

Do not pass `component_version=...` after the recipe name; `just` treats that as
the first positional recipe argument. Avoid `-` in local component versions
because Greengrass Lite splits local recipe filenames on the last hyphen.

Host setup details live in [installation.md](../installation.md). AWS bootstrap and registry steps live in [aws.md](../aws.md).
