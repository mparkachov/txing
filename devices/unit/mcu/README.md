# Unit MCU

The unit MCU builds through the shared stock Zephyr v4.4.0 stack in
[../../../docs/components/mcu.md](../../../docs/components/mcu.md).

The Unit device contract, shadow ownership, MCU boundaries, and operator
workflow are in [../README.md](../README.md).

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
