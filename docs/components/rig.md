# Rig

The rig is the always-on Raspberry Pi coordinator. It bridges Sparkplug lifecycle intent from AWS IoT to BLE rendezvous sessions with the MCU and mirrors board MCP availability for readers.

## Responsibilities

- connect to AWS IoT Core over SigV4-authenticated MQTT over WebSockets
- publish Sparkplug `NBIRTH`, `NDATA`, `NDEATH`, `DBIRTH`, `DDATA`, and `DDEATH`
- accept Sparkplug `DCMD.redcon`
- bridge wakeup-state and sleep-state changes to the MCU over BLE
- write the `mcu` named shadow
- mirror retained MCP descriptor and status topics into the `mcp` named shadow
- derive device REDCON from MCU state, MCP availability, and retained video readiness

Witness, not rig, writes the AWS-side `sparkplug` named shadow projection.

## Current Runtime Model

- managed devices come from the dynamic IoT thing group named by `RIG_NAME`
- startup reads each device `DescribeThing` result, including `attributes.capabilitiesSet`
- named-shadow subscriptions are selected from that `capabilitiesSet`
- Sparkplug lifecycle state is published only on MQTT; the AWS read model is witness-owned
- `mcu.state.reported.power=true` means the wakeup state
- `mcu.state.reported.power=false` means the sleep state with periodic `5 s` BLE rendezvous wakeups

The current contract sources are:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)

## Build And Run

```bash
just rig::check
just rig::build
just rig::run
just rig::debug
```

Useful options:

- `just rig::wake`
- `just rig::sleep`
- `cd rig && ./.venv/bin/rig --no-ble`

`--no-ble` keeps the cloud-side flow active without issuing BLE writes.

## Service Install

```bash
just rig::install-service
sudo journalctl -u rig -f
```

The generated unit:

- runs the built `rig/.venv/bin/rig`
- uses the repo root as `WorkingDirectory`
- loads `config/aws.env` and optional `config/rig.env`
- enables `bluetooth`

Host setup details live in [installation.md](../installation.md). AWS bootstrap and registry steps live in [aws.md](../aws.md).
