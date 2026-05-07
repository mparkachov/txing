# Power Debug Device

`power-debug` is a standalone XIAO nRF54L15 power-floor probe. It intentionally
uses the Seeed PlatformIO Zephyr stack instead of the repo nRF Connect SDK
workspace, nRF-BM wrappers, S115, SoftDevice, BLE, factory data, BME280, battery
measurement, or production weather firmware code.

The goal is to reproduce the Seeed low-power behavior with a repo-local setup:
all PlatformIO packages, the Seeed board definition, Zephyr framework files, and
the GNU Arm Embedded toolchain are installed under `devices/power-debug/`.

## Commands

Install PlatformIO into this subproject:

```sh
just power-debug::firmware-install
```

Build the firmware:

```sh
just power-debug::firmware-check
just power-debug::firmware-paths
```

Manual flash only:

```sh
just power-debug::firmware-flash
```

Agents must not run `firmware-flash`, `pio run -t upload`, OpenOCD, pyOCD, RTT,
or any other hardware-attached command.

## Repo-Local Toolchain Layout

The wrapper forces PlatformIO state into this subproject:

```text
devices/power-debug/.venv/              local Python environment with PlatformIO
devices/power-debug/.platformio-core/   PlatformIO core, Seeed platform, packages
devices/power-debug/.pio/build/         firmware build output
devices/power-debug/.home/              local HOME for PlatformIO settings
devices/power-debug/.pip-cache/         local pip cache
```

The firmware source is:

```text
devices/power-debug/src/main.c
devices/power-debug/zephyr/CMakeLists.txt
devices/power-debug/zephyr/prj.conf
devices/power-debug/zephyr/app.overlay
devices/power-debug/platformio.ini
```

`platformio.ini` uses:

```ini
platform = https://github.com/Seeed-Studio/platform-seeedboards.git
framework = zephyr
board = seeed-xiao-nrf54l15
```

## Firmware Behavior

The image:

1. Boots.
2. Turns the XIAO user LED on for 5 seconds.
3. Turns the user LED off.
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
5. Measure after the LED turns off.

The expected target is current comparable to the Seeed PlatformIO low-power
sample on the same board and measurement setup.

## Notes

- `firmware-check` downloads the Seeed platform and package dependencies into
  `.platformio-core/` on first run. In the validated local build this resolved
  to Seeed Studio platform `1.0.0+sha.9572144`, Zephyr `4.2.1`, and
  `toolchain-gccarmnoneeabi` `1.80201.181220`.
- `firmware-clean` removes only `.pio/` build output. It does not remove the
  installed PlatformIO packages.
- To fully reset the repo-local toolchain, remove `.venv/`, `.platformio-core/`,
  `.home/`, and `.pip-cache/`.
