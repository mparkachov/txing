# Power Device

`power` is the first production-shaped MCU-only device type for the current BLE
wake/sleep firmware. It intentionally has no rig runtime, AWS manifest, shadow
contract, board code, or web adapter yet.

The MCU code is derived from `devices/ble-debug/mcu` and exposes the REDCON BLE
GATT profile used by the Rust rig. The BLE device name is stored in the MCU
factory/NVE area, not compiled into the firmware image.

## Setup

Install host tools manually:

```sh
brew install cmake ninja dtc open-ocd
```

Initialize the repo-local NCS manifest submodule:

```sh
just power::mcu::submodules
```

Create the NCS west workspace, Python environment, and local Zephyr SDK:

```sh
just power::mcu::install
```

Override the Python used to create the NCS environment only when needed:

```sh
export POWER_MCU_NCS_PYTHON=/opt/homebrew/bin/python3.13
```

## Build

The firmware uses stock nRF Connect SDK `west build` with the built-in Seeed
board identifier `xiao_nrf54l15/nrf54l15/cpuapp`. Build-time values live in
`mcu/zephyr/prj.conf`, and REDCON Kconfig symbols are defined in
`mcu/zephyr/Kconfig`. Build and flash commands do not take a profile argument.

```sh
just power::mcu::paths
just power::mcu::check
just power::mcu::build
just power::mcu::flash-check
```

The build output is:

```text
devices/power/mcu/build/ncs-xiao_nrf54l15_cpuapp/zephyr/zephyr/zephyr.hex
```

## Factory/NVE Data

The firmware reads a REDCON factory/NVE record from `0x000f0000`. The current
record stores the BLE device name used in advertising and as the Generic Access
device name. The layout matches the weather MCU factory-data style:

- magic `TXR1`
- version `1`
- device name length
- 26-byte zero-padded printable non-space ASCII device name
- CRC32 over the preceding bytes

Generate and inspect the NVE programming command:

```sh
just power::mcu::nve-hex weather-q8zbgb
just power::mcu::nve-check weather-q8zbgb
```

Program the NVE record manually when hardware is connected:

```sh
just power::mcu::nve-flash weather-q8zbgb
```

## Flash

Manual flash only:

```sh
just power::mcu::flash
```

Agents must not run `flash` or physical BLE tests automatically.

The flash path intentionally uses OpenOCD with the NCS Zephyr Seeed board
configuration. No `nrfutil` runner is used by this subproject.

## Firmware Behavior

- Boots into REDCON `4` sleep state with the XIAO user LED and D1 `power` GPIO off.
- Disables `pdm_imu_pwr` and `vbat_pwr` in BLE idle while leaving the radio path alone.
- Advertises with the NVE-stored BLE device name and the REDCON service UUID.
- REDCON `3` command turns LED and D1 on, requests configured connection params, and notifies state.
- REDCON `4` command or disconnect returns LED and D1 off, disables idle loads, disconnects, and resumes advertising.
- REDCON command payload is `<version, redcon>`; state payload is `<version, redcon, battery_mv_le>`.

The expected manual acceptance run after flashing is:

```sh
just rust-debug::rig::test 5 weather-q8zbgb
```
