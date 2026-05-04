# nRF Connect SDK Bare Metal Toolchain

This directory is the repo-local recipe for building txing firmware against
Nordic's nRF Connect SDK Bare Metal stack. It keeps the BM west checkout,
Zephyr SDK toolchain, Python environment, uv cache, downloads, and local HOME
under this directory.

Pinned versions:

- nRF Connect SDK Bare Metal: `v2.0.0`
- Zephyr SDK: `0.17.4`
- Zephyr SDK toolchain payload: `arm-zephyr-eabi`
- Current weather BM board target: `bm_nrf54l15dk/nrf54l15/cpuapp/s115_softdevice`

The current weather advertising milestone still uses Nordic's BM nRF54L15 DK
board target only to select the nRF54L15 application core and S115 SoftDevice.
The OpenOCD flash target is repo-local and XIAO-compatible.

## Host Prerequisites

Install host tools manually with Homebrew. The `just` targets check for these
tools; they do not install or upgrade Homebrew packages.

```sh
brew install uv just git gperf python@3.13 dtc open-ocd
```

The uv environment defaults to Homebrew `python3.13`. Override with
`TXING_NRF_BM_PYTHON=/path/to/python` if needed.

## Commands

From the repository root:

```sh
just common::nrf_bm::install
just common::nrf_bm::check
just common::nrf_bm::build-weather-advertising
```

`install` creates the uv environment, fetches SDK BM into
`devices/common/mcu/nrf-bm/workspace/`, installs the matching Zephyr SDK under
`devices/common/mcu/nrf-bm/sdk/`, installs Python requirements into
`devices/common/mcu/nrf-bm/.venv`, and builds the weather advertising firmware.

`check` validates the local setup, restores missing Python requirements, and
builds the weather advertising firmware incrementally.

The weather application artifact is:

```text
devices/weather/mcu/build/baremetal-advertising/baremetal/zephyr/zephyr.hex
```

The S115 SoftDevice artifact is:

```text
devices/common/mcu/nrf-bm/workspace/nrf-bm/components/softdevice/nrf54l/s115/s115_nrf54l15_10.0.0_softdevice.hex
```

## Manual Flashing

Flashing remains manual. These targets run OpenOCD and should only be run by a
human with the intended board connected. They do not write the `TXW1` factory
record; keep the existing record or write it with the Zephyr-era flow first.

```sh
just common::nrf_bm::flash-weather-softdevice
just common::nrf_bm::flash-weather-advertising
```

Both targets use:

```text
devices/weather/mcu/support/openocd-nrf54l-cmsis-dap.cfg
```

The application flash target verifies the written image before reset.

## Locality

This setup intentionally avoids user-home scratch paths and CMake package
registration. It downloads the Zephyr SDK minimal archive into this directory,
runs `setup.sh -t arm-zephyr-eabi -h` locally, and points CMake at
`devices/common/mcu/nrf-bm/sdk/zephyr-sdk-0.17.4`.
