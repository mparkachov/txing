# Power Device

`power` is a raspi-compatible txing device type with REDCON BLE firmware,
Sparkplug runtime components, AWS type catalog support, and a simple web
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
just aws::device-deploy <rig-id> power power
```

Use the returned power Thing ID when preparing the MCU factory/NVE data:

```sh
just power::mcu::nve-check <power-thing-id>
just power::mcu::nve-flash <power-thing-id>
```

Deploy rig components after registration:

```sh
just rig::deploy <rig-id>
```

Agents may render `nve-check` commands, but firmware/NVE flashing remains a
manual hardware step.

## MCU Setup

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
device name:

- magic `TXR1`
- version `1`
- device name length
- 26-byte zero-padded printable non-space ASCII device name
- CRC32 over the preceding bytes

Generate and inspect the NVE programming command:

```sh
just power::mcu::nve-hex power-test
just power::mcu::nve-check power-test
```

Program the NVE record manually when hardware is connected:

```sh
just power::mcu::nve-flash power-test
```

## Flash

Manual flash only:

```sh
just power::mcu::flash
```

The flash path intentionally uses OpenOCD with the NCS Zephyr Seeed board
configuration. No `nrfutil` runner is used by this subproject.

## Physical BLE Test

Run the power-specific Rust BLE test after flashing firmware and NVE:

```sh
just power::test 1 <power-thing-id>
```

This runs through Cargo's ignored physical-test harness with terse output and no
log files by default. The test is scoped to the power contract: it connects to
the advertised power Thing ID, wakes the device with REDCON `3`, checks active
battery reports, sends REDCON `4`, keeps the BLE link connected, and waits for
the delayed connected-idle battery report. On macOS the test does not require
the service UUID in the advertisement by default, because CoreBluetooth may
expose only the local name during scanning.

Useful options:

```sh
just power::test 1 <power-thing-id> --logs
just power::test 1 <power-thing-id> --output-dir /tmp/power-connected-idle
just power::test 1 <power-thing-id> --require-service
just power::test 1 <power-thing-id> --idle-report-timeout 90
```

## Firmware Behavior

- Boots into REDCON `4` sleep state with the XIAO user LED and D1 `power` GPIO off.
- Disables `pdm_imu_pwr` and `vbat_pwr` in BLE idle while leaving the radio path alone.
- Advertises with the NVE-stored BLE device name and the REDCON service UUID.
- REDCON `3` command turns LED and D1 on, requests configured connection params, and notifies state.
- REDCON `4` command keeps the BLE connection open, returns LED and D1 off, samples battery, notifies state, and then samples/notifies again every 60 seconds while connected.
- Disconnect returns the MCU to REDCON `4`, cancels the connected-idle battery loop, and resumes advertising.
- REDCON command payload is `<version, redcon>`; state payload is `<version, redcon, battery_mv_le>`.

Manual acceptance after flashing should confirm BLE local name, Sparkplug DBIRTH
with `redcon` and `capability.*`, minute-spaced REDCON `4` reports with
`batteryMv` in the `power` named shadow, REDCON `3` wakeup, and idle current
with ADC suspended between samples.
