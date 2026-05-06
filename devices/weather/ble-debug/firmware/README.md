# Weather BLE Debug S115 Firmware

This is a separate SoftDevice S115 bare-metal debug firmware variant for the
weather MCU. It is built with the same repo-local `sdk-nrf-bm` toolchain as the
production weather bare-metal firmware, but it lives under
`devices/weather/ble-debug/firmware/` so connection behavior can be changed
without touching production code.

The `sdk-nrf-bm` build still uses Zephyr's CMake, Kconfig, and kernel utility
APIs. The default power-measurement image compiles logging/RTT/console out. The
BLE stack is S115 SoftDevice, not Zephyr Bluetooth.

## Behavior

- Reads the existing `TXW1` factory record at `0x000f0000`.
- Advertises the factory Thing name as the complete local name.
- Exposes the txing weather service and command/state/measurement
  characteristics.
- Remains connected in REDCON `4` idle state.
- Drives high-drive `power` on D1/P1.05 high and mirrors it to the XIAO user
  LED immediately for REDCON `3`.
- Normalizes requested REDCON `1` and `2` to actual REDCON `3`.
- Sends a state notification immediately after every accepted command.
- Initializes the BME280 only after `power` is high, then sends one BME280
  measurement notification per second while active.
- Samples battery voltage through the XIAO battery divider while active and
  includes it in state and measurement payloads.
- Drives `power` on D1/P1.05 low, turns the user LED off, resets BME280 state,
  and stops measurements for REDCON `4`.
- Restarts connectable advertising after disconnect.

## XIAO Pin Mapping

The debug app owns these board-level pins:

```text
power output        D1 / P1.05   active high, high-drive, mirrors user LED
BME280 Grove SDA    D4 / P1.10
BME280 Grove SCL    D5 / P1.11
VBAT ADC input      AIN7 / P1.14
VBAT divider enable P1.15        active high
```

D0 maps to P1.04 on the XIAO connector, but the BM board configuration also
uses P1.04 as UART TX. The default power image has no logging backend and keeps
the BM UARTE console disabled, but `power` is intentionally on D1/P1.05 so the
GPIO contract is independent of that board-config mismatch.

Battery measurement follows Seeed's XIAO nRF54L15 battery circuit: enable the
divider on P1.15, sample AIN7/P1.14, then apply the 2:1 divider correction.
The CLI prints non-zero values as `batteryMv=...`.

The default debug idle connection parameters are intentionally low-power:

```text
idle interval=1000 ms
idle latency=4
idle supervision=20 s
active interval=100 ms
active latency=0
active supervision=10 s
initial_request_delay=250 ms
```

The firmware requests the active parameters as setup parameters after the
initial request delay, then switches to the selected idle parameters only after
the central subscribes to debug notifications. This keeps Raspberry Pi / BlueZ
service discovery on a responsive link while still allowing REDCON `4` to move
to the long low-power interval once setup is done.

In REDCON `4`, the app leaves BME280 and SAADC shut down, disables
scan-request events, compiles out Zephyr logging/RTT/console backends, does not
run periodic diagnostics, does not sample battery, and uses the S115 WFE idle
sequence instead of a polling loop after the connection parameter request has
settled. Enable `CONFIG_TXING_WEATHER_IDLE_DIAG_ENABLE`,
`CONFIG_TXING_WEATHER_IDLE_BATTERY_REPORT_ENABLE`,
`CONFIG_TXING_WEATHER_IDLE_LOG_FLUSH_ENABLE`, or `CONFIG_TXING_WEATHER_SCAN_REQ_NOTIFY`
only for focused debugging because each one wakes the CPU or keeps extra
peripherals/log traffic active.

The SoftDevice random auto-seed path stays enabled through PSA/CRACEN. S115 on
nRF54L15 needs it for reliable BLE startup; disabling it can produce a build
that boots but does not advertise.

The BM XIAO board defconfig enables all nrfx drivers for convenience. This app
overrides that list for current measurement builds and keeps only CLOCK, POWER,
GRTC, SYSTICK, RRAMC, TWIM, and SAADC.

The production unit firmware already had a board-low-power step that parks
unused LEDs, IMU/mic rails, and external flash. This debug app mirrors that
idea for XIAO nRF54L15: BLE profiles explicitly drive the unused XIAO Sense
PDM/IMU rail P0.01 low at boot. The RF-switch helper pins P2.03 and P2.05 are
left untouched in BLE profiles because the radio path may depend on them.

For board floor-current isolation, build `floor-systemoff-5s`:

```sh
just weather::ble-debug::firmware-app floor-systemoff-5s
```

This is an app-only profile for measurement. It does not start SoftDevice, BLE,
advertising, GATT, BME280, or the battery ADC. It drives `power` D1/P1.05 and
VBAT enable P1.15 low, drives XIAO Sense PDM/IMU power P0.01 low, parks the
RF-switch helper pins, releases sensor pins, turns the user LED on for 5
seconds after boot, then turns the LED off, disables RAM retention, and enters
nRF54 System OFF with `NRF_REGULATORS->SYSTEMOFF`. After flashing, disconnect
the debugger/probe for the current measurement; debug mode can simulate System
OFF and keep current artificially high.

## Build

Install the shared BM toolchain once:

```sh
just weather::ble-debug::firmware-install
```

Build this debug firmware:

```sh
just weather::ble-debug::firmware-check
```

Print paths:

```sh
just weather::ble-debug::firmware-paths
```

## Manual Flashing Only

Agents must not run flash targets.

Manual-only targets are provided for the user:

```sh
just weather::ble-debug::firmware-softdevice
just weather::ble-debug::firmware-nve weather-q8zbgb
just weather::ble-debug::firmware-app lowpower-1000-4-20
just weather::ble-debug::firmware-verify-softdevice
just weather::ble-debug::firmware-verify-nve weather-q8zbgb
just weather::ble-debug::firmware-verify-app lowpower-1000-4-20
```

`firmware-softdevice` writes only S115. `firmware-nve weather-q8zbgb` writes
only the `TXW1` NVE/factory record containing the advertised Thing name.
`firmware-app lowpower-1000-4-20` writes only the application image built with
that BLE parameter profile. These targets use the fast OpenOCD
SoftDevice-native flash path and merged HEX files; they do not use pyOCD
chunked programming.
