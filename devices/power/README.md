# Power Device

`power` is a raspi-compatible txing device type with REDCON BLE firmware,
standalone rig daemon support, AWS type catalog support, and a simple web
adapter. It is separate from `weather`; weather stays active as its own device
type.

The MCU stores its BLE device name in the factory/NVE area. The rig expects that
name to match the AWS Thing ID assigned to the power device.

## AWS And Deployment

Deploy the shared AWS stack and type catalog:

```sh
just aws::deploy
```

Register a power device on a raspi rig:

```sh
just aws::deploy-device <rig-id> power power
```

Use the returned power Thing ID when preparing the MCU factory/NVE data:

```sh
just power::mcu::check-nve <power-thing-id>
just power::mcu::flash-nve <power-thing-id>
```

Restart rig daemons after registration if the rig inventory should refresh
immediately:

```sh
just rig::restart <config-dir>
```

Agents may render `check-nve` commands, but firmware/NVE flashing remains a
manual hardware step.

## MCU Setup

Install host tools manually:

```sh
brew install cmake ninja dtc open-ocd arm-none-eabi-gcc
```

Create the repo-local Python environment and stock Zephyr west workspace:

```sh
just power::mcu::install
```

The power MCU workspace is local to `devices/power/mcu/.zephyr-workspace` and
is pinned to stock Zephyr `v4.4.0`, the latest stable Zephyr release at the time
this power trial was created. The recipes keep `HOME`, pip cache, Zephyr cache,
ccache, and temporary files inside the repository while installing and building.

## Build

The firmware uses stock Zephyr `west build` with the built-in Seeed board
identifier `xiao_nrf54l15/nrf54l15/cpuapp`. Build-time values live in
`mcu/zephyr/prj.conf`; app-specific Kconfig includes the shared REDCON symbols
from `devices/common/mcu/xiao_nrf54l15/Kconfig`. The power CMake target links
the same `devices/common/mcu/xiao_nrf54l15/src/redcon.c` implementation used by
`unit` and `weather`; power-specific behavior is limited to the local
`mcu/src/main.c` ops, `mcu/zephyr/prj.conf`, and devicetree overlay. Build and
flash commands do not take a profile argument.

```sh
just power::mcu::paths
just power::mcu::check
just power::mcu::build
just power::mcu::check-flash
```

The build output is:

```text
devices/power/mcu/build/zephyr-xiao_nrf54l15_cpuapp/zephyr/zephyr.hex
```

## Factory/NVE Data

The firmware reads a REDCON factory/NVE record from `0x000f0000`. The current
record stores the BLE device name used in advertising and as the Generic Access
device name:

- magic `TXR1`
- version `1`
- device name length
- 26-byte zero-padded printable non-space ASCII device name
- CRC32 over the preceding bytes

Generate and inspect the NVE programming command:

```sh
just power::mcu::build-nve-hex power-test
just power::mcu::check-nve power-test
```

Program the NVE record manually when hardware is connected:

```sh
just power::mcu::flash-nve power-test
```

## Flash

Manual flash only:

```sh
just power::mcu::flash
```

The flash path intentionally uses OpenOCD with the stock Zephyr Seeed board
configuration. No `nrfutil` runner is used by this subproject.

## Firmware Behavior

- Boots into REDCON `4` sleep state with the XIAO user LED and D1 `power` GPIO off.
- Disables `pdm_imu_pwr` and `vbat_pwr` in BLE idle while leaving the radio path alone.
- Advertises with the NVE-stored BLE device name and the REDCON service UUID.
- REDCON `3` command turns LED and D1 on, requests configured connection params, and notifies state.
- REDCON `4` command keeps the BLE connection open, returns LED and D1 off, samples battery, notifies the power measurement, and then samples/notifies again every 60 seconds while connected.
- Disconnect preserves REDCON `3` when the device is in wakeup state, keeps LED and D1 on, and resumes advertising. Disconnect in REDCON `4` stays in REDCON `4`, cancels the connected-idle battery loop, and resumes advertising.
- REDCON command payload is `<version, redcon>`; state payload is `<version, redcon>`.
- Power measurement payload is `<version, battery_mv>` on `f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100`.

Manual acceptance after flashing should confirm BLE local name, Sparkplug DBIRTH
with `redcon` and `capability.*`, minute-spaced REDCON `4` reports with
`batteryMv` in the `power` named shadow, REDCON `3` wakeup, and idle current
with ADC suspended between samples.
