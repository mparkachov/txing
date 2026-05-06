# Weather BLE Debug S115 Firmware

This is a separate SoftDevice S115 bare-metal debug firmware variant for the
weather MCU. It is built with the same repo-local `sdk-nrf-bm` toolchain as the
production weather bare-metal firmware, but it lives under
`devices/weather/ble-debug/firmware/` so connection behavior can be changed
without touching production code.

The `sdk-nrf-bm` build still uses Zephyr's CMake, Kconfig, logging, and kernel
utility APIs. The BLE stack is S115 SoftDevice, not Zephyr Bluetooth.

## Behavior

- Reads the existing `TXW1` factory record at `0x000f0000`.
- Advertises the factory Thing name as the complete local name.
- Exposes the txing weather service and command/state/measurement
  characteristics.
- Remains connected in REDCON `4` idle state.
- Turns the XIAO user LED on immediately for REDCON `3`.
- Normalizes requested REDCON `1` and `2` to actual REDCON `3`.
- Sends a state notification immediately after every accepted command.
- Sends one BME280 measurement notification per second while active.
- Turns the user LED off and stops measurements for REDCON `4`.
- Restarts connectable advertising after disconnect.

Debug idle connection parameters are intentionally conservative:

```text
interval=100 ms
latency=0
supervision=6 s
initial_request_delay=250 ms
```

The firmware requests those parameters either after the central subscribes to
debug notifications or after the initial request delay, whichever happens
first. The early request gives Raspberry Pi / BlueZ service discovery a longer
supervision timeout before the link can drop on weak RSSI.

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
just weather::ble-debug::firmware-app baseline-100-0-6
just weather::ble-debug::firmware-verify-softdevice
just weather::ble-debug::firmware-verify-nve weather-q8zbgb
just weather::ble-debug::firmware-verify-app baseline-100-0-6
just weather::ble-debug::firmware-rtt
```

`firmware-softdevice` writes only S115. `firmware-nve weather-q8zbgb` writes
only the `TXW1` NVE/factory record containing the advertised Thing name.
`firmware-app baseline-100-0-6` writes only the application image built with
that BLE parameter profile. These targets use the fast OpenOCD
SoftDevice-native flash path and merged HEX files; they do not use pyOCD
chunked programming.
