# MCU

Firmware for the nRF52840-based watch layer.

## Current Behavior

- reset default: sleep state
- external wakeup state contract: `power=true`
- external sleep state contract: `power=false`
- sleep state uses RTC-driven low-power idle with periodic `5 s` rendezvous wakeups and a short advertising window
- wakeup state stays BLE-connectable
- battery and sleep state are exposed through the current BLE state report

The MCU-specific integration contract is
[devices/unit/docs/device-rig-shadow-spec.md](../../devices/unit/docs/device-rig-shadow-spec.md).

## Build Artifacts

Run from the repo root:

```bash
just mcu::check
just mcu::build
just mcu::bin
just mcu::uf2
```

Or from `devices/unit/mcu/`:

```bash
just check
just build
just bin
just uf2
```

## Flashing

Current manual flash paths:

```bash
just mcu::flash-probe
just mcu::flash-uf2
just mcu::log
```

Notes:

- the application is linked at `0x27000`
- avoid full-chip erase flows unless you intentionally want to wipe the bootloader or other non-application flash
- firmware flashing remains a manual user action
