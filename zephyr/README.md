# Zephyr / nRF Connect SDK Toolchain

This directory is a reproducible local recipe for building Zephyr firmware for
`xiao_nrf54l15/nrf54l15/cpuapp` on macOS Apple Silicon. It keeps the nRF
Connect SDK checkout, Zephyr SDK, Python environment, uv cache, downloads, and
build output under this directory and ignores all generated content in git.

Pinned versions:

- nRF Connect SDK: `v3.3.0`
- Zephyr SDK: `0.17.4`
- Zephyr SDK toolchain payload: `arm-zephyr-eabi`
- Validation board: `xiao_nrf54l15/nrf54l15/cpuapp`

## Host Prerequisites

Install host tools manually with Homebrew. The `just` targets only check for
these tools; they do not install or upgrade Homebrew packages.

```sh
brew install uv just git cmake ninja gperf python python-tk ccache dtc libmagic wget open-ocd
```

The initial `check` target builds a sample and does not use QEMU. Install QEMU
manually later if you need Zephyr emulation:

```sh
brew install qemu
```

## Commands

From the repository root:

```sh
just zephyr::install
just zephyr::check
just zephyr::check-flash
```

`install` creates the uv environment, fetches NCS into `zephyr/workspace/`,
installs the matching Zephyr SDK under `zephyr/sdk/`, installs the Python
requirements into `zephyr/.venv`, and does a pristine Zephyr blinky build.

`check` validates the local setup by restoring missing local Python
requirements and running an incremental build. When the build directory is
missing or the recipe configuration changes, it does a one-time pristine
configure/build; steady-state checks reuse the existing build directory:

```sh
west build -d zephyr/build/blinky-xiao_nrf54l15_cpuapp
```

The expected build artifact is:

```text
zephyr/build/blinky-xiao_nrf54l15_cpuapp/blinky/zephyr/zephyr.elf
```

The image output also includes
`zephyr/build/blinky-xiao_nrf54l15_cpuapp/blinky/zephyr/zephyr.hex` and
`zephyr/build/blinky-xiao_nrf54l15_cpuapp/blinky/zephyr/zephyr.bin`.

`check-flash` runs the same validation/build path as `check`, then flashes the
compiled build to the connected device with:

```sh
west flash --no-rebuild -d zephyr/build/blinky-xiao_nrf54l15_cpuapp
```

Run this target manually only when the intended device is connected.

## External Projects

External Zephyr applications do not need to copy or vendor the NCS checkout or
Zephyr SDK. Run `just zephyr::install` once from this repository, then point the
external build at this directory's local workspace, SDK, and Python environment.

From this repository root, set this environment in the shell that runs external
builds:

```sh
export TXING_ZEPHYR_ROOT="$(pwd)/zephyr"
export UV_CACHE_DIR="$TXING_ZEPHYR_ROOT/.uv-cache"
export HOME="$TXING_ZEPHYR_ROOT/.home"
export ZEPHYR_BASE="$TXING_ZEPHYR_ROOT/workspace/zephyr"
export ZEPHYR_SDK_INSTALL_DIR="$TXING_ZEPHYR_ROOT/sdk/zephyr-sdk-0.17.4"
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export PATH="$TXING_ZEPHYR_ROOT/.venv/bin:$PATH"
```

Run `west` from the local Zephyr workspace so NCS modules are resolved from
`zephyr/workspace/`:

```sh
cd "$ZEPHYR_BASE"
```

Use these board identifiers:

```text
xiao_nrf54l15/nrf54l15/cpuapp  # Seeed Studio XIAO nRF54L15, application core
xiao_ble                       # Seeed Studio XIAO nRF52840
xiao_ble/nrf52840/sense         # Seeed Studio XIAO nRF52840 Sense
```

There is no `xiao_nrf52840` board identifier in this pinned Zephyr tree; the
XIAO nRF52840 board family is named `xiao_ble`.

Build an external app for XIAO nRF54L15:

```sh
west build -p auto \
  -b xiao_nrf54l15/nrf54l15/cpuapp \
  /absolute/path/to/external/app \
  -d "$TXING_ZEPHYR_ROOT/build/<app>-xiao_nrf54l15_cpuapp"
```

Build the same external app for XIAO nRF52840:

```sh
west build -p auto \
  -b xiao_ble \
  /absolute/path/to/external/app \
  -d "$TXING_ZEPHYR_ROOT/build/<app>-xiao_ble"
```

Build for XIAO nRF52840 Sense:

```sh
west build -p auto \
  -b xiao_ble/nrf52840/sense \
  /absolute/path/to/external/app \
  -d "$TXING_ZEPHYR_ROOT/build/<app>-xiao_ble_sense"
```

Use a separate build directory for each board. Flashing remains a manual step:

```sh
west flash --no-rebuild -d "$TXING_ZEPHYR_ROOT/build/<app>-xiao_ble"
```

If Python imports fail after manually resyncing the uv environment, run
`just zephyr::check` once from this repository to restore the NCS Python
requirements into `zephyr/.venv`.

## Locality

This recipe intentionally avoids `west sdk install` because that command runs
SDK CMake package registration. Instead, the script downloads the Zephyr SDK
minimal archive, runs `setup.sh -t arm-zephyr-eabi -h` locally, and passes
`ZEPHYR_SDK_INSTALL_DIR=zephyr/sdk/zephyr-sdk-0.17.4` to builds.

The check build passes `SB_CONFIG_PARTITION_MANAGER=n` through
`zephyr/config/blinky-sysbuild.conf` so the validation sample uses DTS-based
partitioning and does not emit NCS's partition-manager deprecation warning.

The subprocess environment also points `HOME` at `zephyr/.home` so west and
CMake do not need to write to the real user home directory during these targets.

Flashing/programming hardware remains manual; `install` and `check` never flash.
