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

- REDCON `4`: connected idle, no BME280 telemetry
- REDCON `3`: LED on, BME280 measurement notification once per second
- requested REDCON `1` or `2`: accepted as active and reported as actual `3`

Agents must not run the flash target. Use it only manually with the intended
board connected.

## Bare-metal advertising milestone

`baremetal/` contains an advertising-only S115 scaffold for replacing the Zephyr
firmware. It reads the same `TXW1` factory record and advertises the AWS IoT
Thing name as the primary BLE local name. It does not yet implement the weather
GATT service, BME280, or sleep-state rendezvous cycle.

Build it with Nordic's `sdk-nrf-bm` workspace:

```sh
PATH="$HOME/Downloads/nrf-bm-tools/bin:$PWD/zephyr/.venv/bin:$PATH" \
ZEPHYR_SDK_INSTALL_DIR="$PWD/zephyr/sdk/zephyr-sdk-0.17.4" \
ZEPHYR_TOOLCHAIN_VARIANT=zephyr \
NRF_BM_ROOT="$HOME/Downloads/nrf-bm-v2.0.0" \
just --justfile devices/weather/mcu/justfile bm-check
```

Do not flash from automation; use the generated artifacts manually.
