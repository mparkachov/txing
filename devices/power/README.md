# Power Device

`power` is the first production-shaped MCU-only device type for the current BLE
wake/sleep firmware. It intentionally has no rig runtime, AWS manifest, shadow
contract, board code, or web adapter yet.

The MCU code is derived from `devices/ble-debug/mcu` and keeps the current
weather-compatible BLE GATT protocol so the Rust rig stability test can run
unchanged against `weather-q8zbgb`.

## Setup

Install host tools manually:

```sh
brew install arm-none-eabi-gcc arm-none-eabi-binutils open-ocd
```

Initialize repo-local firmware submodules:

```sh
just power::mcu::submodules
```

Create the Zephyr Python environment and validate the Homebrew toolchain:

```sh
just power::mcu::install
```

Override the compiler prefix only when needed:

```sh
export POWER_MCU_CROSS_COMPILE=/opt/homebrew/bin/arm-none-eabi-
```

## Build

The firmware has one config in `mcu/conf/mcu.yaml`; build and flash commands do
not take a profile argument.

```sh
just power::mcu::paths
just power::mcu::check
just power::mcu::build
just power::mcu::flash-check
```

The build output is:

```text
devices/power/mcu/build/zephyr-xiao_nrf54l15_cpuapp-brew/zephyr/zephyr.hex
```

## Flash

Manual flash only:

```sh
just power::mcu::flash
```

Agents must not run `flash` or physical BLE tests automatically.

## Firmware Behavior

- Boots into REDCON `4` sleep state with the XIAO user LED and D1 `power` GPIO off.
- Disables `pdm_imu_pwr` and `vbat_pwr` in BLE idle while leaving the radio path alone.
- Advertises as `weather-q8zbgb` with the weather service UUID and GATT service.
- REDCON `3` command turns LED and D1 on, requests supplied connection params, and notifies state.
- REDCON `4` command or disconnect returns LED and D1 off, disables idle loads, disconnects, and resumes advertising.

The expected manual acceptance run after flashing is:

```sh
just rust-debug::rig::test 5 weather-q8zbgb --conn-profile stable-100-0-20
```
