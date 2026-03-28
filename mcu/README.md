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
- `sleep=true`: RTC-driven system-on low-power idle with periodic `5 s` rendezvous wakeups and a short `1 s` advertising window
- `sleep=false`: stay in the wakeup state and remain BLE-connectable
- BLE state report transport:
  - advertising manufacturer data carries `TX` plus the 3-byte MCU State Report while disconnected
  - the GATT State Report characteristic carries the same 3-byte payload while connected
- LED indication:
  - `sleep=true` -> LED OFF
  - `sleep=false` -> LED ON
- Sleep-mode power policy:
  - stays in `System ON`; it does not use `System OFF`, because RTC wakeups every `5 s` are required
  - puts the onboard QSPI flash into deep power-down at boot and parks the flash pins
  - keeps the onboard IMU and microphone power-enable GPIOs low
  - parks unused onboard sensor/flash pins and keeps the unused RGB/charge LEDs driven OFF
  - keeps the battery divider enabled because Seeed documents that driving `P0.14` high can expose `P0.31` to battery voltage during charging

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
just flash-probe

# Build release firmware and attach RTT/defmt logs
just log

# Build UF2 and copy to the mounted board bootloader drive
just flash-uf2
```

`just flash-probe` uses `probe-rs run` with `--no-catch-reset --no-catch-hardfault`, suppresses target RTT output, and detaches after a short startup window. This is the current working SWD flash path for the reset issue.

Use `just log` when you want an attached probe-rs RTT session for troubleshooting.

The linked firmware already starts at `0x27000` via [`memory.x`](./memory.x), so probe-rs flashes the application region without requiring a manual binary base address.

The double-tap reset USB mass-storage bootloader should remain available after `just flash-probe`. Do not use `probe-rs erase`, `probe-rs download --chip-erase`, or `--allow-erase-all` unless you intentionally want to wipe the on-board bootloader/other non-application flash.

If you have more than one debug probe attached, use the standard probe-rs environment variables such as `PROBE_RS_PROBE`, `PROBE_RS_SPEED`, or `PROBE_RS_CONNECT_UNDER_RESET` when running `just flash-probe`.

## Checks

```bash
# Firmware compile check
just check
```
