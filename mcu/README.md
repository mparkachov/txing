# txing

Firmware for nRF52840 (Seeed XIAO BLE Sense) with BLE sleep control.

## Project Structure

- `src/main.rs`: device firmware
- `xtask/`: host-side utility commands wrapped by `just` recipes
- `../docs/device-gateway-shadow-spec.md`: gateway contract (Shadow + BLE only)
- `../docs/txing-shadow.schema.json`: canonical Thing Shadow JSON schema

## Firmware Behavior (Summary)

- Device state:
  - `battery_pct` (currently hardcoded to `50`)
  - `sleep` (`true`/`false`)
- Reset/power-cycle default: `sleep=true`, `battery_pct=50`
- `sleep=true`: low-power periodic wake/listen
- `sleep=false`: stay awake and BLE-connectable
- LED indication:
  - `sleep=true` -> LED OFF
  - `sleep=false` -> LED ON

## Prerequisites

- Rust toolchain with `thumbv7em-none-eabihf` target
- `uf2conv` available in `PATH` (for UF2 generation/flash)
- Board mounted at `/Volumes/XIAO-SENSE` for `flash`

Run from `mcu/` with `just <recipe>`, or from repo root with `just mcu::<recipe>`.

## Build and Flash

```bash
# Build release firmware
just build

# Build binary artifact (.bin)
just bin

# Build UF2 artifact (.uf2)
just uf2

# Build UF2 and copy to mounted board
just flash
```

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
