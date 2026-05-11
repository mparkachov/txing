# Weather MCU

This directory builds the `weather` txing firmware for:

```text
xiao_nrf54l15/nrf54l15/cpuapp
```

The board is a Seeed Studio XIAO nRF54L15 with a Grove BME280 on the XIAO I2C
connector. The weather firmware no longer uses Matter, Thread, `chip-tool`, or
online provisioning. The rig talks to the device over BLE connected-idle.

The AWS IoT Thing ID is written as factory data during flashing and is used as
the BLE advertised local name:

```sh
just weather::mcu::flash weather-q8zbgb
```

Factory data is written into the merged HEX image at
`WEATHER_FACTORY_DATA_ADDRESS` (default `0x000f0000`) with:

- magic `TXW1`
- version `1`
- ASCII Thing ID length and bytes
- CRC32 over the preceding fields

`just weather::mcu::check` builds the firmware. `just weather::mcu::verify` can
optionally receive the same Thing ID to include factory data in the expected
image:

```sh
just weather::mcu::check
just weather::mcu::verify weather-q8zbgb
```

The BLE contract is defined in `app/src/weather_ble_protocol.*`:

- REDCON command/state use payload version `2` and carry only `<version, redcon>`
- power measurement `f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100` carries `<version, battery_mv>`
- weather measurement `f6b4b004-7b32-4d2d-9f4b-4ff0a2b8f100` carries `<version, temperature_centi, pressure_pa, humidity_centi>`
- REDCON `4`: connected idle, battery and weather measurement every 60 seconds
- REDCON `3`: LED on, battery and weather measurement every 10 seconds
- requested REDCON `1` or `2`: accepted as active and reported as actual `3`

Agents must not run the flash target. Use it only manually with the intended
board connected.
