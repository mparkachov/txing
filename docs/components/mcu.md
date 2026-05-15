# MCU

Firmware for the XIAO nRF54L15 MCU used by `unit`, `power`, and `weather`.
Shared REDCON BLE, factory/NVE, battery, advertising, connection, and idle
hardware handling lives in `devices/common/mcu/xiao_nrf54l15`.

## Current Behavior

- target board: `xiao_nrf54l15/nrf54l15/cpuapp`
- firmware stack: NCS/Zephyr through `devices/common/mcu/ncs`
- shared REDCON app entrypoint: `txing_redcon_run(&ops)`
- D1 / `gpio1 5` is the active-high enable for app hardware
- reset default: `REDCON 4`, D1 off, LED off, load regulators disabled, ADC suspended
- `REDCON 1`, `2`, and `3`: D1/LED on, state reported, battery sampled/notified, periodic active battery reports
- `REDCON 4`: D1 off, BLE remains connected when possible, idle battery reports every `60 s`, advertising resumes after disconnect
- `unit` accepts REDCON `1`/`2`/`3`/`4` and preserves the current REDCON level across BLE disconnect
- `power` accepts REDCON `3`/`4` and preserves REDCON `3` across BLE disconnect
- `weather` accepts REDCON `4` idempotently, rejects other command levels, and exposes the weather measurement characteristic
- factory/NVE record at `0x000f0000` stores the AWS Thing ID used as the BLE
  advertised identity name with the `TXR1` layout

The integration contract is [devices/unit/docs/device-rig-shadow-spec.md](../../devices/unit/docs/device-rig-shadow-spec.md).

## Build Artifacts

Run from the repo root:

```bash
just unit::mcu::paths
just unit::mcu::check
just unit::mcu::build
just unit::mcu::build-nve-hex unit-test
just power::mcu::check
just weather::mcu::check
```

Or from `devices/unit/mcu/`:

```bash
just paths
just check
just build
just build-nve-hex unit-test
```

## Flashing

Firmware and NVE flashing remain manual user actions. To print the exact commands without programming hardware:

```bash
just unit::mcu::check-flash
just unit::mcu::check-nve unit-test
```

Manual flash recipes are available as:

```bash
just unit::mcu::flash
just unit::mcu::flash-nve <thing-name>
```
