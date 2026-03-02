# txing

Firmware for nRF52840 (Seeed XIAO BLE Sense) with BLE sleep control.

## Project Structure

- `src/main.rs`: device firmware
- `xtask/`: host-side utility commands (`cargo fw ...`)
- `docs/device-gateway-shadow-spec.md`: gateway contract (Shadow + BLE only)

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
- macOS host for `cargo fw` alias in `.cargo/config.toml` (`aarch64-apple-darwin`)

## Build and Flash

```bash
# Build release firmware
cargo fw build

# Build binary artifact (.bin)
cargo fw bin

# Build UF2 artifact (.uf2)
cargo fw uf2

# Build UF2 and copy to mounted board
cargo fw flash
```

## Local BLE Debug Commands

Direct BLE control without Shadow/gateway:

```bash
# Set sleep=false (wake / keep awake)
cargo fw wakeup

# Set sleep=true (return to low power)
cargo fw sleep
```

Optional flags:

```bash
cargo fw wakeup --name txing --scan-timeout 20
cargo fw sleep --name txing --scan-timeout 20
```

Advanced command:

```bash
cargo fw ble-sleep --sleep false --name txing --scan-timeout 20
cargo fw ble-sleep --sleep true --name txing --scan-timeout 20
```

## Checks

```bash
# Firmware compile check
cargo check --target thumbv7em-none-eabihf

# xtask compile check (host)
cargo check --manifest-path xtask/Cargo.toml --target aarch64-apple-darwin
```
