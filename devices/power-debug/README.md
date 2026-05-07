# Power Debug Device

`power-debug` is a standalone XIAO nRF54L15 power-floor probe. It intentionally
stays separate from the repo nRF Connect SDK workspace, nRF-BM wrappers, S115,
SoftDevice, BLE, factory data, BME280, battery measurement, and production
weather firmware code.

The current known-good path is the Seeed PlatformIO Zephyr build. A second native
Zephyr path is provided to remove the PlatformIO build dependency while keeping
the same Zephyr version, Seeed board definition, and GNU Arm Embedded compiler.
A third Homebrew toolchain path uses the same native Zephyr sources with the
user-installed Homebrew `arm-none-eabi-gcc` and `arm-none-eabi-binutils`.

## PlatformIO Reference Build

This is the preserved known-good build path. It keeps all PlatformIO state under
`devices/power-debug/`.

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

## Native Zephyr Build

The native path uses git submodules under `devices/common/mcu/`:

```text
devices/common/mcu/zephyr                       Zephyr 4.2.1
devices/common/mcu/seeed-platform              Seeed board platform
devices/common/mcu/modules/hal/cmsis           Zephyr CMSIS module
devices/common/mcu/modules/hal/cmsis_6         Zephyr CMSIS_6 module
devices/common/mcu/modules/hal/nordic          Zephyr Nordic HAL module
devices/common/mcu/modules/lib/picolibc        Zephyr picolibc module
```

Initialize those submodules:

```sh
just power-debug::firmware-native-submodules
```

Create the native Zephyr Python environment:

```sh
just power-debug::firmware-native-install
```

The native build intentionally refuses to use Homebrew/system `arm-none-eabi-gcc`
because the known-good compiler is GNU Arm Embedded GCC `8.2.1`. Put that
toolchain at:

```text
devices/common/mcu/toolchain-gccarmnoneeabi/
```

If that path is absent, the wrapper falls back to the repo-local PlatformIO
package with the same GCC version:

```text
devices/power-debug/.platformio-core/packages/toolchain-gccarmnoneeabi/
```

You can also set:

```sh
export GNUARMEMB_TOOLCHAIN_PATH=/Users/Maxim/Developer/txing/devices/common/mcu/toolchain-gccarmnoneeabi
```

The expected compiler binary is:

```text
$GNUARMEMB_TOOLCHAIN_PATH/bin/arm-none-eabi-gcc
```

Build with native Zephyr/CMake/Ninja:

```sh
just power-debug::firmware-native-check
just power-debug::firmware-native-paths
```

Manual native flash only:

```sh
just power-debug::firmware-native-flash
```

The native flash recipe does not use Zephyr's generated `flash` target because
that target requires a west workspace. It builds the native image and then calls
the Seeed XIAO OpenOCD configuration directly with the generated
`zephyr/zephyr.hex`.

To print the exact OpenOCD command without touching hardware:

```sh
just power-debug::firmware-native-flash-command
```

Native flash uses the repo-local OpenOCD package installed by the PlatformIO
reference setup:

```text
devices/power-debug/.platformio-core/packages/tool-openocd/bin/openocd
```

If needed, override it with repo-local paths only:

```sh
export POWER_DEBUG_OPENOCD=/Users/Maxim/Developer/txing/devices/power-debug/.platformio-core/packages/tool-openocd/bin/openocd
export POWER_DEBUG_OPENOCD_SCRIPTS=/Users/Maxim/Developer/txing/devices/power-debug/.platformio-core/packages/tool-openocd/openocd/scripts
```

Agents must not run `firmware-native-flash` or any other hardware-attached
command.

## Homebrew Toolchain Zephyr Build

The Homebrew path is intentionally separate from the known-good GCC `8.2.1`
native build. It uses the same Zephyr submodules and board files, but configures
Zephyr as an external cross compiler:

```text
ZEPHYR_TOOLCHAIN_VARIANT=cross-compile
CROSS_COMPILE=/opt/homebrew/bin/arm-none-eabi-
```

Install the toolchain manually:

```sh
brew install arm-none-eabi-gcc arm-none-eabi-binutils
```

Then initialize the same native Zephyr Python environment and validate the
Homebrew toolchain:

```sh
just power-debug::firmware-brew-install
```

Build with Homebrew GCC/binutils:

```sh
just power-debug::firmware-brew-check
just power-debug::firmware-brew-paths
```

Manual Homebrew flash only:

```sh
just power-debug::firmware-brew-flash
```

To print the exact OpenOCD command without touching hardware:

```sh
just power-debug::firmware-brew-flash-command
```

Agents must not run `firmware-brew-flash` or any other hardware-attached
command.

The default Homebrew prefix is detected from `/opt/homebrew/bin/arm-none-eabi-`
or `/usr/local/bin/arm-none-eabi-`. Override it only when needed:

```sh
export POWER_DEBUG_BREW_CROSS_COMPILE=/opt/homebrew/bin/arm-none-eabi-
```

The Homebrew path currently depends on module picolibc. It is not a general
replacement for firmware that requires a toolchain-provided newlib sysroot.

## PlatformIO Toolchain Layout

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

## Native Toolchain Layout

The native wrapper uses:

```text
devices/power-debug/.native-venv/               local Python environment
devices/power-debug/.native-pip-cache/          local pip cache
devices/power-debug/.native-zephyr-cache/       local Zephyr cache
devices/power-debug/.native-ccache/             local ccache dir if ccache is present
devices/power-debug/build/zephyr-xiao_nrf54l15_cpuapp/
devices/common/mcu/zephyr/                      Zephyr submodule
devices/common/mcu/seeed-platform/              Seeed board submodule
devices/common/mcu/modules/...                  Zephyr module submodules
devices/common/mcu/toolchain-gccarmnoneeabi/    expected GCC 8.2.1 toolchain
devices/power-debug/.platformio-core/packages/toolchain-gccarmnoneeabi/
                                                fallback repo-local GCC 8.2.1 package
devices/power-debug/.platformio-core/packages/tool-openocd/
                                                repo-local OpenOCD for manual native flash
```

Native CMake is configured with:

```text
BOARD=xiao_nrf54l15/nrf54l15/cpuapp
ZEPHYR_BASE=devices/common/mcu/zephyr
BOARD_ROOT=devices/common/mcu/seeed-platform/zephyr
ZEPHYR_CACHE_DIR=devices/power-debug/.native-zephyr-cache
ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb
USE_CCACHE=0
CCACHE_DISABLE=1
CCACHE_PROGRAM=CCACHE_PROGRAM-NOTFOUND
CCACHE_DIR=devices/power-debug/.native-ccache
```

The Homebrew build uses the same native Zephyr state and a separate build
directory:

```text
devices/power-debug/build/zephyr-xiao_nrf54l15_cpuapp-brew/
```

It is configured with:

```text
ZEPHYR_TOOLCHAIN_VARIANT=cross-compile
CROSS_COMPILE=/opt/homebrew/bin/arm-none-eabi-
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

When testing the Homebrew variant, use:

```sh
just power-debug::firmware-brew-check
just power-debug::firmware-brew-flash
```

Compare the post-LED-off battery current against the known-good PlatformIO and
GCC `8.2.1` native images before treating the Homebrew image as equivalent.

## Notes

- `firmware-check` downloads the Seeed platform and package dependencies into
  `.platformio-core/` on first run. In the validated local build this resolved
  to Seeed Studio platform `1.0.0+sha.9572144`, Zephyr `4.2.1`, and
  `toolchain-gccarmnoneeabi` `1.80201.181220`.
- `firmware-native-check` does not use PlatformIO. It uses the Zephyr and Seeed
  git submodules under `devices/common/mcu/` plus a repo-local or explicitly
  provided GNU Arm Embedded GCC `8.2.1` path under this repository.
- `firmware-brew-check` uses the same Zephyr and Seeed git submodules as
  `firmware-native-check`, but selects Zephyr `cross-compile` and the
  user-installed Homebrew `arm-none-eabi-*` tools.
- If `devices/common/mcu/toolchain-gccarmnoneeabi/` is absent,
  `firmware-native-check` falls back to the repo-local PlatformIO GCC package.
- `firmware-native-flash` bypasses `cmake --build --target flash` and `west
  flash`; this repository intentionally is not a west workspace.
- `firmware-brew-flash` uses the same direct OpenOCD flow as
  `firmware-native-flash`, but flashes the Homebrew-built `zephyr.hex`.
- `firmware-clean` removes only `.pio/` build output. It does not remove the
  installed PlatformIO packages.
- `firmware-native-clean` removes only native Zephyr build output.
- To fully reset the PlatformIO reference toolchain, remove `.venv/`,
  `.platformio-core/`, `.home/`, and `.pip-cache/`.
- To reset the native wrapper environment, remove `.native-venv/` and
  `.native-pip-cache/`. To reset Zephyr's native CMake cache, remove
  `.native-zephyr-cache/`. Do not remove the shared submodules unless you intend
  to re-run `firmware-native-submodules`.
