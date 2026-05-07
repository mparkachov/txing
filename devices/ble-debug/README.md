# BLE Debug Device

`ble-debug` is a standalone XIAO nRF54L15 BLE idle power probe. Most profiles
are advertising-only. The `gatt-1280-*` profiles add a minimal connectable
weather GATT surface for idle connection testing. There is still no real
wake/sleep behavior, no telemetry stream, no BME280, no battery sampling, no
factory/NVE data, no S115, no SoftDevice, no nRF-BM, and no PlatformIO.

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

Build the default lowest-current firmware:

```sh
just ble-debug::mcu::check
just ble-debug::mcu::build
```

Build a specific advertising profile:

```sh
just ble-debug::mcu::build tx-minus20
just ble-debug::mcu::build tx-0
just ble-debug::mcu::build named-1280
just ble-debug::mcu::build service-1280
just ble-debug::mcu::build service-1280-tx4
just ble-debug::mcu::build service-1280-tx8
just ble-debug::mcu::build gatt-1280-tx0
just ble-debug::mcu::build gatt-1280-tx4
just ble-debug::mcu::build gatt-1280-tx8
just ble-debug::mcu::build service-320
```

Inspect resolved paths:

```sh
just ble-debug::mcu::paths
just ble-debug::mcu::paths service-1280
```

Build outputs are profile-specific:

```text
devices/ble-debug/mcu/build/zephyr-xiao_nrf54l15_cpuapp-brew-<profile>/zephyr/zephyr.hex
```

## Flash

Manual flash only:

```sh
just ble-debug::mcu::flash
just ble-debug::mcu::flash service-1280
```

`flash` does not rebuild. Run `just ble-debug::mcu::build` first when the source
changed.

Agents must not run `flash` or any other hardware-attached command.

To check the exact flash command without touching hardware:

```sh
just ble-debug::mcu::flash-check
just ble-debug::mcu::flash-check service-1280
```

The flash command intentionally starts with plain `openocd`, so `brew upgrade`
is enough to pick up the latest OpenOCD available in your shell `PATH`.

## Firmware Behavior

All profiles:

1. Boots with the XIAO user LED and D1 `power` GPIO off.
2. Disables `pdm_imu_pwr` and `vbat_pwr`.
3. Leaves `rfsw_pwr` and `rfsw_ctl` unchanged for the BLE radio path.
4. Starts Zephyr Bluetooth.
5. Advertises indefinitely, except connectable advertising pauses during a
   connection and restarts after disconnect.

This Zephyr revision has a broken nRF54L static TX-power default path for the
lowest power values, so the app enables dynamic TX power control and programs
the advertising handle with the Zephyr vendor HCI command before advertising
starts.

Profiles are ordered from lowest current toward easiest detection:

| Profile | Interval | TX power | Scannable | Payload |
| --- | ---: | ---: | --- | --- |
| `low-current` | 10.24 s | -46 dBm | no | name only |
| `tx-minus20` | 10.24 s | -20 dBm | no | name only |
| `tx-0` | 10.24 s | 0 dBm | no | name only |
| `named-1280` | 1.28 s | 0 dBm | no | name only |
| `service-1280` | 1.28 s | 0 dBm | yes | name + weather UUID scan response |
| `service-1280-tx4` | 1.28 s | +4 dBm | yes | name + weather UUID scan response |
| `service-1280-tx8` | 1.28 s | +8 dBm | yes | name + weather UUID scan response |
| `gatt-1280-tx0` | 1.28 s | 0 dBm | connectable | name + weather UUID scan response + weather GATT |
| `gatt-1280-tx4` | 1.28 s | +4 dBm | connectable | name + weather UUID scan response + weather GATT |
| `gatt-1280-tx8` | 1.28 s | +8 dBm | connectable | name + weather UUID scan response + weather GATT |
| `service-320` | 320 ms | 0 dBm | yes | name + weather UUID scan response |

All profiles include flags and the complete local name:

```text
weather-q8zbgb
```

Only `service-*` profiles include the weather service UUID in scan response.
Use those when you need active scanners to report `service=1`. The lowest
current profiles intentionally omit scan response and service UUID because those
increase current.

The `gatt-1280-*` profiles expose the existing weather BLE UUIDs:

```text
service      f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100
command      f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100  write with response
state        f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100  read + notify
measurement  f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100  read + notify
```

The GATT profile stays in idle state. State reads return REDCON `4` with no
BME280 data and zero battery voltage. Command writes accept valid protocol
payloads so central-side write paths can be tested, but REDCON `3` does not
wake the board, enable D1 `power`, or produce measurements.

Real wake/sleep behavior, telemetry, BME280, and battery measurement remain out
of scope for this profile.

## Measurement Flow

1. Build with `just ble-debug::mcu::check <profile>`.
2. Flash manually with `just ble-debug::mcu::flash <profile>`.
3. Disconnect USB and debug wiring.
4. Power through the battery pads and multimeter.
5. Run a BLE scan long enough for the selected interval and confirm `weather-q8zbgb`.
6. Measure current while the device is advertising, with user LED and D1 `power` off.

Recommended detectability ladder:

```sh
just ble-debug::mcu::build tx-minus20
just ble-debug::mcu::flash-check tx-minus20

just ble-debug::mcu::build tx-0
just ble-debug::mcu::flash-check tx-0

just ble-debug::mcu::build named-1280
just ble-debug::mcu::flash-check named-1280

just ble-debug::mcu::build service-1280
just ble-debug::mcu::flash-check service-1280

just ble-debug::mcu::build service-1280-tx4
just ble-debug::mcu::flash-check service-1280-tx4

just ble-debug::mcu::build service-1280-tx8
just ble-debug::mcu::flash-check service-1280-tx8

just ble-debug::mcu::build gatt-1280-tx0
just ble-debug::mcu::flash-check gatt-1280-tx0

just ble-debug::mcu::build gatt-1280-tx4
just ble-debug::mcu::flash-check gatt-1280-tx4

just ble-debug::mcu::build gatt-1280-tx8
just ble-debug::mcu::flash-check gatt-1280-tx8
```

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
