# MCU

Firmware for the XIAO nRF54L15 MCU used by `unit`, `power`, and `weather`.
Shared REDCON BLE, factory/NVE, battery, advertising, connection, and idle
hardware handling lives in `devices/common/mcu/xiao_nrf54l15`.

## Shared Stack Invariant

The active MCU firmware targets are `devices/unit/mcu`, `devices/power/mcu`,
and `devices/weather/mcu`. `devices/template/mcu` is only a scaffold and does
not build firmware.

All active MCU targets use the same shared stack:

- each target's `zephyr/CMakeLists.txt` sets `TXING_XIAO_NRF54L15_DIR` to
  `devices/common/mcu/xiao_nrf54l15`
- each target compiles `${TXING_XIAO_NRF54L15_DIR}/src/redcon.c`
- each target includes `${TXING_XIAO_NRF54L15_DIR}/include`
- shared setup and hardware actions run through root `mcu` recipes backed by
  `devices/common/mcu/scripts/stock_zephyr_mcu.py`
- each target's `justfile` keeps device-owned `build` and `clean` recipes only
- the shared `mcu::nve` recipe uses
  `devices/common/mcu/xiao_nrf54l15/scripts/redcon_nve.py`

Device-specific behavior belongs in the local `src/main.c` hooks passed through
`struct txing_redcon_ops`, local `zephyr/prj.conf`, and local devicetree
overlays. The shared REDCON implementation remains single-source: active XIAO
nRF54L15 targets share `redcon.c`, the REDCON UUID/payload handling, and the
common stock Zephyr install/build path.

## Current Behavior

- target board: `xiao_nrf54l15/nrf54l15/cpuapp`
- firmware stack: stock Zephyr v4.4.0 through `devices/common/mcu/zephyr`
- shared stock Zephyr build driver:
  `devices/common/mcu/scripts/stock_zephyr_mcu.py`
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
just mcu::install
just mcu::check
just unit::mcu::build
just power::mcu::build
just weather::mcu::build
```

Or from `devices/unit/mcu/`:

```bash
just build
```

## Flashing

Firmware and NVE flashing remain manual user actions:

```bash
just mcu::flash unit
just mcu::nve <thing-name>
```
