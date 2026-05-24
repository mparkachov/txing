# Weather MCU

This directory builds the `weather` txing firmware for:

```text
xiao_nrf54l15/nrf54l15/cpuapp
```

The board is a Seeed Studio XIAO nRF54L15 with a BME280 on I2C. BME280 power is
switched by XIAO D1, and firmware only powers the sensor during a measurement.

The firmware uses the shared REDCON BLE service implementation:

- build/install/check go through the shared stock Zephyr v4.4.0 stack in
  `devices/common/mcu`
- the Zephyr target links `devices/common/mcu/xiao_nrf54l15/src/redcon.c`
- command/state UUIDs use payload version `2`
- state is always `<2, 4>`
- REDCON `4` command is accepted as an idempotent connected-idle command
- REDCON `3` and all other command levels are rejected by the GATT write
- power measurement `f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100` carries `<version, battery_mv>`
- weather measurement `f6b4b004-7b32-4d2d-9f4b-4ff0a2b8f100` carries `<version, temperature_centi_c, pressure_pa, humidity_centi_percent>`
- connected REDCON `4` reports battery and BME280 measurements every 60 seconds

Factory/NVE data is shared REDCON factory data at `0x000f0000`:

- magic `TXR1`
- version `1`
- printable non-space ASCII BLE device name length and bytes
- CRC32 over the preceding fields

Build firmware:

```sh
just mcu::install
just mcu::check
just weather::mcu::build
```

Firmware and NVE flashing remain manual hardware steps:

```sh
just mcu::flash weather
just mcu::nve weather-q8zbgb
```
