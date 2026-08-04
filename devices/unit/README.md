# Unit Device

The `unit` is the current physical device type. Its board, MCU, rig, and shadow
contracts are documented separately so each component has a single owner.

## Device contracts

- [Unit device-rig shadow contract](docs/device-rig-shadow-spec.md)
- [Unit Thing Shadow model](docs/thing-shadow.md)
- [Board video contract](docs/board-video.md)
- [Shared MCU stack](../../docs/components/mcu.md)

`rig` owns the `ble` and `power` named-shadow contracts. The MCU implements the
shared REDCON protocol; it must not fork `redcon.c`, the REDCON UUID or payload
handling, or the shared XIAO nRF54L15 Zephyr install and build path.

## MCU firmware

The Unit MCU uses the shared stock Zephyr v4.4.0 stack for target board
`xiao_nrf54l15/nrf54l15/cpuapp`.

Run setup, preflight, and builds from the repository root:

```sh
just mcu::install
just mcu::check
just unit::mcu::build
```

Firmware and NVE flashing remain manual operator actions:

```sh
just unit::mcu::flash
just mcu::nve unit-test
```
