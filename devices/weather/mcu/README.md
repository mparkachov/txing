# Weather MCU

This directory builds the `weather` txing firmware for:

```text
xiao_nrf54l15/nrf54l15/cpuapp
```

The connected sensor is a Grove BME280 on the XIAO I2C connector. The build
uses the local repository Zephyr/NCS recipe under `zephyr/`, a repo-owned
common Matter MCU foundation under `devices/common/mcu/matter/`, and the small
tracked weather app under `devices/weather/mcu/app/`. Generated Matter C++,
signing keys, merged HEX files, flash chunks, and verification bins stay under
`devices/weather/mcu/build/` and are not stored in git.

The tracked app owns the `.zap` and `.matter` data model files. During CMake
configure, the common foundation copies the matching pregenerated ZAP C++ from
the supported NCS `matter_weather_station` application into `build/`, so the
recipe does not require `zap-cli` as an extra host tool.

The common Matter foundation owns:

- Matter server startup, commissioning, task dispatch, identify handling, and
  status LED behavior
- Zephyr/OpenThread/Matter ICD low-power policy; weather code does not manually
  sleep
- standard Matter attribute publishers for Temperature Measurement, Pressure
  Measurement, Relative Humidity Measurement, and Power Source
- MCUboot/sysbuild signing setup, using an ignored local ED25519 development
  key instead of MCUboot's bundled debug key
- flash and verify helpers for the XIAO nRF54L15 CMSIS-DAP path

The weather app owns only BME280 readiness, sampling, conversion, and endpoint
selection. It exposes standard Matter attributes only:

- endpoint `1`: `TemperatureMeasurement.MeasuredValue`
- endpoint `2`: `RelativeHumidityMeasurement.MeasuredValue`
- endpoint `3`: `PressureMeasurement.MeasuredValue`
- endpoint `0`: `PowerSource.BatVoltage`

`batteryMv` is not a Matter attribute. It is a rig/Sparkplug projection name
for the standard Matter `PowerSource.BatVoltage` value, expressed in mV.

The XIAO board overlay enables the Grove BME280 at `0x76`, restores the full
nRF54L15 RRAM/SRAM span needed by this board, and keeps the watchdog node
enabled. The MCUboot overlay reserves a 62 KiB boot partition to satisfy
nRF54L flash-protection limits while keeping the app slot address.

If the Grove module is strapped to `0x77`, update
`config/xiao_nrf54l15_bme280.overlay` before building.

Commands from the repository root:

```sh
just zephyr::install
just weather::mcu::check
```

The Matter sample also requires `gn` on the host. Install it manually with
Homebrew if `just weather::mcu::check` reports it missing:

```sh
brew install gn
```

Manual flashing command:

```sh
just weather::mcu::flash
```

The default flash runner is uv-managed pyOCD `0.44.x`. It performs a mass erase
before loading the merged HEX because XIAO nRF54L15 CMSIS-DAP/OpenOCD direct
RRAM writes can fail mid-image on larger Matter firmware. The default pyOCD SWD
clock is `50000`.

The pyOCD load is split into 16 KiB HEX chunks by default so the on-board
CMSIS-DAP probe does not need to sustain one long programming transfer for the
whole Matter image. Chunks are aligned to 4 KiB erase sectors so a later chunk
does not erase data programmed by an earlier chunk. To change or disable
chunking:

```sh
PYOCD_CHUNK_SIZE=0x2000 just weather::mcu::flash
PYOCD_CHUNK_SIZE=0 just weather::mcu::flash
```

Each chunk is retried up to three times if the CMSIS-DAP link drops:

```sh
PYOCD_CHUNK_RETRIES=5 PYOCD_RETRY_DELAY_SECONDS=3 just weather::mcu::flash
```

If the command reaches the final chunk and exits without a Python traceback or
`error: Recipe`, pyOCD has reported that all chunks were programmed. This is
still a programming status, not a byte-for-byte read-back verification. To
compare flash contents against the generated merged HEX image, run:

```sh
just weather::mcu::verify
```

The verify target rebuilds if needed, splits the same merged HEX into the same
sector-aligned chunks, then uses pyOCD `compare` reads for each chunk. It does
not erase or program flash, but it does connect to the target; press reset or
power-cycle the board afterward if the core is left halted.

By default, each chunk is loaded with `--no-reset`; press reset or power-cycle
the board after a successful flash. To ask pyOCD to reset when all chunks are
loaded:

```sh
PYOCD_RESET_AFTER_LOAD=1 just weather::mcu::flash
```

If multiple CMSIS-DAP probes are connected, select one explicitly:

```sh
PYOCD_PROBE_UID=<probe-serial> just weather::mcu::flash
```

If the previous image leaves the core in a bad state, try a slower pyOCD clock
and a different connect mode:

```sh
PYOCD_FREQUENCY=25000 PYOCD_CONNECT=pre-reset just weather::mcu::flash
```

To skip the pyOCD mass erase:

```sh
PYOCD_MASS_ERASE=0 just weather::mcu::flash
```

Homebrew-managed OpenOCD remains available as a fallback. This path uses the
XIAO board configuration from the local Zephyr workspace and unbuffered
nRF54L15 RRAM writes (`OPENOCD_RRAMC_CONFIG=0x1`) instead of Zephyr's default
buffered board helper (`0x101`):

```sh
WEATHER_MCU_FLASH_RUNNER=openocd just weather::mcu::flash
```

If OpenOCD programming is stable and you want to try a faster clock:

```sh
WEATHER_MCU_FLASH_RUNNER=openocd OPENOCD_FREQUENCY=250 just weather::mcu::flash
```

Agents must not run the flash target. Use it only when the intended board is
connected.
