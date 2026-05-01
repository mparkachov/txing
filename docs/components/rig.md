# Rig

The rig is the always-on Raspberry Pi coordinator. It bridges Sparkplug lifecycle intent from AWS IoT to BLE rendezvous sessions with the MCU and mirrors board MCP availability for readers.

## Current Responsibilities

- connect to AWS IoT Core over SigV4-authenticated MQTT over WebSockets
- publish Sparkplug node lifecycle for the rig edge node with `NBIRTH` and `NDEATH`
- publish Sparkplug device lifecycle for managed txing/unit things with `DBIRTH`, `DDATA`, and `DDEATH`
- accept Sparkplug `DCMD.redcon`
- bridge wakeup-state and sleep-state changes to the MCU over BLE
- write the `mcu` named shadow
- mirror retained MCP descriptor and status topics into the `mcp` named shadow
- derive device REDCON from MCU state, MCP availability, and retained video readiness

Witness, not rig, writes the AWS-side `sparkplug` named shadow projection.
Hard invariant: `rig = Sparkplug edge node = Greengrass Lite core`. The rig
itself must never be represented by Sparkplug device `DBIRTH` or `DDEATH`.

## Greengrass Lite Split

The rig now has a Greengrass-oriented component split in addition to the legacy
single-process CLI:

- `dev.txing.device.unit.SparkplugManager`
  - owns AWS registry discovery, shadows, retained MCP/video reads, REDCON derivation, and Sparkplug lifecycle
  - defines Greengrass service running plus direct AWS IoT MQTT connectivity as the rig edge-node `NBIRTH` condition
  - publishes explicit rig edge-node `NDEATH` on graceful shutdown and configures `NDEATH` as MQTT Last Will
  - uses direct per-device AWS IoT MQTT sessions so `DBIRTH` and `DDEATH` are coupled to each device session lifecycle
- `dev.txing.device.unit.ConnectivityBle`
  - owns BLE scanning, rendezvous presence, one-at-a-time GATT sessions, and MCU wake/sleep state reports
  - communicates with the manager only through local Greengrass pub/sub topics under `dev/txing/rig/v1/connectivity/#`
  - never publishes Sparkplug node lifecycle
- future `dev.txing.rig.ConnectivityMatter`
  - should implement the same connectivity contract using Matter ICD reachability instead of BLE rendezvous
  - must not publish Sparkplug node lifecycle

## Current Runtime Model

- managed devices come from the dynamic IoT thing group named by `RIG_NAME`
- startup reads each device `DescribeThing` result, including `attributes.capabilitiesSet`
- named-shadow subscriptions are selected from that `capabilitiesSet`
- Sparkplug lifecycle state is published only on MQTT; the AWS read model is witness-owned
- Greengrass core/device/component status is service observability only; it is not the txing lifecycle source of truth
- `mcu.state.reported.power=true` means the wakeup state
- `mcu.state.reported.power=false` means the sleep state with periodic `5 s` BLE rendezvous wakeups

The current contract sources are:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)

## Build And Run

`rig::build-native` requires the Greengrass Lite native toolchain on the rig
host. On Raspberry Pi OS Lite/Trixie, install at least `cmake`,
`build-essential`, `pkg-config`, `libssl-dev`, `libcurl4-openssl-dev`,
`uuid-dev`, `libzip-dev`, `libsqlite3-dev`, `libyaml-dev`, `libsystemd-dev`,
`libevent-dev`, `liburiparser-dev`, and `cgroup-tools`.

```bash
just rig::check
just rig::build-native
just rig::build
just rig::run
just rig::debug
```

`just rig::check` validates AWS control-plane access plus certificate-backed
AWS IoT connectivity from `config/certs/rig/`. It intentionally does not inspect
systemd or `/var/lib/greengrass`; `just rig::install-service` owns creating the
installed Greengrass filesystem state.

Useful options:

- `just rig::wake`
- `just rig::sleep`
- `cd rig && ./.venv/bin/rig --no-ble`

`--no-ble` keeps the cloud-side flow active without issuing BLE writes.

## Service Install

```bash
just rig::build-native
just rig::build
just rig::install-service
just rig::deploy
sudo systemctl status --with-dependencies greengrass-lite.target
```

`rig::build-native` builds Greengrass Lite with `GG_LOG_LEVEL=INFO` so the
standard Greengrass daemons do not flood journald with debug traces.

The install target no longer creates or removes a custom `rig.service`. It
enables `bluetooth`, resolves the configured rig thing and Greengrass token
exchange settings from AWS, writes `/etc/greengrass/config.yaml`, installs the
native Greengrass Lite build using the upstream CMake install target, and starts
the standard `greengrass-lite.target` through Greengrass Lite's
`misc/run_nucleus` script. Rig behavior comes from Greengrass deployments of
`dev.txing.device.unit.SparkplugManager` and connectivity adapter components.

Use `just rig::deploy` after changing or pulling rig code; it depends
on `just rig::build` and then stages a new local component artifact under
`rig/build/greengrass-local`. That staging directory is intentionally kept until
the next deploy because Greengrass Lite copies artifacts asynchronously. Use
`just rig::restart` only when you want to restart Bluetooth and the existing
Greengrass Lite systemd units without changing the deployed component version.

Host setup details live in [installation.md](../installation.md). AWS bootstrap and registry steps live in [aws.md](../aws.md).
