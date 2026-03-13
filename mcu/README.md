# txing

Firmware for nRF52840 (Seeed XIAO BLE Sense) with BLE sleep control.

## Project Structure

- `src/main.rs`: device firmware
- `../docs/device-gateway-shadow-spec.md`: gateway contract (Shadow + BLE only)
- `../docs/txing-shadow.schema.json`: canonical Thing Shadow JSON schema

## Firmware Behavior (Summary)

- Device state:
  - `battery_mv` (measured BAT voltage estimate in millivolts)
  - `sleep` (`true`/`false`)
- External terminology:
  - `sleep=true` corresponds to the sleep state / `power=false`
  - `sleep=false` corresponds to the wakeup state / `power=true`
- Reset/power-cycle default: `sleep=true`
- `sleep=true`: RTC-driven low-power idle with periodic `5 s` rendezvous wakeups and a brief advertising window
- `sleep=false`: stay in the wakeup state and remain BLE-connectable
- BLE state report transport:
  - advertising manufacturer data carries `TX` plus the 3-byte MCU State Report while disconnected
  - the GATT State Report characteristic carries the same 3-byte payload while connected
- LED indication:
  - `sleep=true` -> LED OFF
  - `sleep=false` -> LED ON

## Prerequisites

- Rust toolchain with `thumbv7em-none-eabihf` target
- `cargo objcopy` available in `PATH` (for `.bin` and `.uf2` generation)
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

# Build release firmware and flash it over SWD with probe-rs
just flash

# Explicit alias for SWD flashing
just probe-flash

# Build release firmware and attach RTT/defmt logs
just log

# Build UF2 and copy to the mounted board bootloader drive
just flash-uf2
```

`just flash` uses `probe-rs download` with the release ELF directly. The linked firmware already starts at `0x27000` via [`memory.x`](./memory.x), so probe-rs flashes the application region without requiring a manual binary base address.

The double-tap reset USB mass-storage bootloader should remain available after `just flash`. Do not use `probe-rs erase`, `probe-rs download --chip-erase`, or `--allow-erase-all` unless you intentionally want to wipe the on-board bootloader/other non-application flash.

If you have more than one debug probe attached, use the standard probe-rs environment variables such as `PROBE_RS_PROBE`, `PROBE_RS_SPEED`, or `PROBE_RS_CONNECT_UNDER_RESET` when running `just flash`.

## Checks

```bash
# Firmware compile check
just check
```
