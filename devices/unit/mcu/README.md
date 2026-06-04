# Unit MCU

The unit MCU builds through the shared stock Zephyr v4.4.0 stack in
[../../../docs/components/mcu.md](../../../docs/components/mcu.md).

Common commands from the repository root:

```sh
just mcu::install
just mcu::check
just unit::mcu::build
```

Firmware and NVE flashing are manual operator actions:

```sh
just unit::mcu::flash
just mcu::nve unit-test
```

Related docs:

- [Unit device-rig shadow contract](../docs/device-rig-shadow-spec.md)
- [Unit thing shadow model](../docs/thing-shadow.md)
