# BLE Debug Device

`ble-debug` is a standalone XIAO nRF54L15 BLE idle power probe. V1 is deliberately
advertising-only: no connection handling, no GATT service, no wake/sleep command,
no telemetry, no BME280, no battery sampling, no factory/NVE data, no S115,
no SoftDevice, no nRF-BM, and no PlatformIO.

The only supported build path uses:

```text
devices/common/mcu/zephyr                       Zephyr 4.2.1
devices/common/mcu/seeed-platform              Seeed board platform
devices/common/mcu/modules/hal/cmsis           Zephyr CMSIS module
devices/common/mcu/modules/hal/cmsis_6         Zephyr CMSIS_6 module
devices/common/mcu/modules/hal/nordic          Zephyr Nordic HAL module
devices/common/mcu/modules/lib/picolibc        Zephyr picolibc module
Homebrew arm-none-eabi-gcc/binutils            compiler and binutils
openocd from PATH                              manual flashing only
```

There is no alternate external build path in this subproject.

## Setup

Install host tools manually:

```sh
brew install arm-none-eabi-gcc arm-none-eabi-binutils open-ocd
```

Initialize repo-local firmware submodules:

```sh
just ble-debug::mcu::submodules
```

Create the Zephyr Python environment and validate the Homebrew toolchain:

```sh
just ble-debug::mcu::install
```

The default toolchain prefix is detected from `/opt/homebrew/bin/arm-none-eabi-`,
`/usr/local/bin/arm-none-eabi-`, or `arm-none-eabi-gcc` in `PATH`. Override it
only when needed:

```sh
export BLE_DEBUG_CROSS_COMPILE=/opt/homebrew/bin/arm-none-eabi-
```

## Build

Build the firmware:

```sh
just ble-debug::mcu::check
just ble-debug::mcu::build
```

Inspect resolved paths:

```sh
just ble-debug::mcu::paths
```

The build output is:

```text
devices/ble-debug/mcu/build/zephyr-xiao_nrf54l15_cpuapp-brew/zephyr/zephyr.hex
```

## Flash

Manual flash only:

```sh
just ble-debug::mcu::flash
```

`flash` does not rebuild. Run `just ble-debug::mcu::build` first when the source
changed.

Agents must not run `flash` or any other hardware-attached command.

To check the exact flash command without touching hardware:

```sh
just ble-debug::mcu::flash-check
```

The flash command intentionally starts with plain `openocd`, so `brew upgrade`
is enough to pick up the latest OpenOCD available in your shell `PATH`.

## Firmware Behavior

The image:

1. Boots with the XIAO user LED and D1 `power` GPIO off.
2. Disables `pdm_imu_pwr` and `vbat_pwr`.
3. Leaves `rfsw_pwr` and `rfsw_ctl` unchanged for the BLE radio path.
4. Starts Zephyr Bluetooth.
5. Advertises indefinitely as non-connectable and scannable.

Advertising data contains flags and the complete local name:

```text
weather-q8zbgb
```

Scan response data contains the weather service UUID:

```text
f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100
```

Connection, GATT, wake/sleep commands, telemetry, BME280, and battery
measurement are intentionally out of scope for V1.

## Measurement Flow

1. Build with `just ble-debug::mcu::check`.
2. Flash manually with `just ble-debug::mcu::flash`.
3. Disconnect USB and debug wiring.
4. Power through the battery pads and multimeter.
5. Run an active BLE scan and confirm `weather-q8zbgb` with the weather service UUID.
6. Measure current while the device is advertising, with user LED and D1 `power` off.

## Generated State

Generated files stay under:

```text
devices/ble-debug/mcu/.venv/
devices/ble-debug/mcu/.pip-cache/
devices/ble-debug/mcu/.zephyr-cache/
devices/ble-debug/mcu/.ccache/
devices/ble-debug/mcu/build/
```

Clean build output:

```sh
just ble-debug::mcu::clean
```
