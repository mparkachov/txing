# Unit MCU

The unit MCU builds through the shared stock Zephyr v4.4.0 stack in
[../../../docs/components/mcu.md](../../../docs/components/mcu.md).

Common commands from the repository root:

```sh
just mcu::install
just unit::mcu::paths
just unit::mcu::build
just unit::mcu::check
just mcu::check-flash unit
just mcu::check-nve unit-test
```

Firmware and NVE flashing are manual operator actions:

```sh
just mcu::flash unit
just mcu::nve unit-test
```

Related docs:

- [Unit device-rig shadow contract](../docs/device-rig-shadow-spec.md)
- [Unit thing shadow model](../docs/thing-shadow.md)
