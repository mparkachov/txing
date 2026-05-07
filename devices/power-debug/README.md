# Power Debug Device

`power-debug` is a standalone XIAO nRF54L15 power-floor probe. It intentionally
stays separate from the repo NCS workspace, nRF-BM wrappers, S115, SoftDevice,
BLE, factory data, BME280, battery measurement, and production weather firmware.

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
just power-debug::firmware-submodules
```

Create the Zephyr Python environment and validate the Homebrew toolchain:

```sh
just power-debug::firmware-install
```

The default toolchain prefix is detected from `/opt/homebrew/bin/arm-none-eabi-`,
`/usr/local/bin/arm-none-eabi-`, or `arm-none-eabi-gcc` in `PATH`. Override it
only when needed:

```sh
export POWER_DEBUG_CROSS_COMPILE=/opt/homebrew/bin/arm-none-eabi-
```

## Build

Build the firmware:

```sh
just power-debug::firmware-check
```

Inspect resolved paths:

```sh
just power-debug::firmware-paths
```

The build output is:

```text
devices/power-debug/build/zephyr-xiao_nrf54l15_cpuapp-brew/zephyr/zephyr.hex
```

## Flash

Manual flash only:

```sh
just power-debug::firmware-flash
```

Agents must not run `firmware-flash` or any other hardware-attached command.

To print the exact command without touching hardware:

```sh
just power-debug::firmware-flash-command
```

The flash command intentionally starts with plain `openocd`, so `brew upgrade`
is enough to pick up the latest OpenOCD available in your shell `PATH`.

## Firmware Behavior

The image:

1. Boots.
2. Turns the XIAO user LED and D1 `power` GPIO on for 5 seconds.
3. Turns the user LED and D1 `power` GPIO off.
4. Disables `pdm_imu_pwr`, `rfsw_pwr`, and `vbat_pwr`.
5. Suspends the console if present.
6. Clears the reset cause.
7. Enters Zephyr `sys_poweroff()`.

The overlay mirrors the known Seeed low-power sample by deleting
`regulator-boot-on` from:

```text
pdm_imu_pwr
rfsw_pwr
vbat_pwr
```

`rfsw_ctl` is intentionally left unchanged.

## Measurement Flow

1. Build with `just power-debug::firmware-check`.
2. Flash manually with `just power-debug::firmware-flash`.
3. Disconnect USB and debug wiring.
4. Power through the battery pads and multimeter.
5. Measure after the LED and D1 `power` pin turn off.

The expected target is current comparable to the Seeed low-power sample on the
same board and measurement setup.

## Generated State

Generated files stay under:

```text
devices/power-debug/.native-venv/
devices/power-debug/.native-pip-cache/
devices/power-debug/.native-zephyr-cache/
devices/power-debug/.native-ccache/
devices/power-debug/build/
```

Clean build output:

```sh
just power-debug::firmware-clean
```
