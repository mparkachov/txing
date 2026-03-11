# txing

Firmware for nRF52840 (Seeed XIAO BLE Sense) with BLE sleep control.

## Project Structure

- `src/main.rs`: device firmware
- `xtask/`: host-side utility commands wrapped by `just` recipes
- `../docs/device-gateway-shadow-spec.md`: gateway contract (Shadow + BLE only)
- `../docs/txing-shadow.schema.json`: canonical Thing Shadow JSON schema

## Firmware Behavior (Summary)

- Device state:
  - `battery_pct` (estimated from measured BAT voltage on the XIAO divider)
  - `battery_volt` (measured BAT voltage estimate in volts)
  - `sleep` (`true`/`false`)
- Reset/power-cycle default: `sleep=true`, `battery_pct` derived from the current battery voltage
- `sleep=true`: low-power periodic wake/listen
- `sleep=false`: stay awake and BLE-connectable
- LED indication:
  - `sleep=true` -> LED OFF
  - `sleep=false` -> LED ON

## Prerequisites

- Rust toolchain with `thumbv7em-none-eabihf` target
- `probe-rs` available in `PATH` (for SWD flashing)
- `uf2conv` available in `PATH` (for UF2 generation)
- Board mounted at `/Volumes/XIAO-SENSE` only when using `flash-uf2`

Run from `mcu/` with `just <recipe>`, or from repo root with `just mcu::<recipe>`.

## Build and Flash

```bash
# Build release firmware
just build

# Build binary artifact (.bin)
just bin

# Build UF2 artifact (.uf2)
just uf2

# Build binary and flash it over SWD with probe-rs
just flash

# Explicit alias for SWD flashing
just probe-flash

# Build UF2 and copy to the mounted board bootloader drive
just flash-uf2
```

`just flash` uses `probe-rs download` with the raw application binary at base address `0x27000`, which matches [`memory.x`](./memory.x) and keeps the existing SoftDevice + UF2 bootloader layout intact.

The double-tap reset USB mass-storage bootloader should remain available after `just flash`. Do not use `probe-rs erase`, `probe-rs download --chip-erase`, or `--allow-erase-all` unless you intentionally want to wipe the on-board bootloader/other non-application flash.

If you have more than one debug probe attached, use the standard probe-rs environment variables such as `PROBE_RS_PROBE`, `PROBE_RS_SPEED`, or `PROBE_RS_CONNECT_UNDER_RESET` when running `just flash`.

## Local BLE Debug Commands

Direct BLE control without Shadow/gateway:

```bash
# Set sleep=false (wake / keep awake)
just wakeup

# Set sleep=true (return to low power)
just sleep
```

Optional flags:

```bash
just wakeup --name txing --scan-timeout 20
just sleep --name txing --scan-timeout 20
```

Advanced command:

```bash
just ble-sleep --sleep false --name txing --scan-timeout 20
just ble-sleep --sleep true --name txing --scan-timeout 20
```

## Checks

```bash
# Firmware compile check
just check

# xtask compile check (host target)
just check-xtask
```
