---
id: doc-7
title: 'Constraints: MCU stock Zephyr shared stack'
type: guide
created_date: '2026-05-24 13:20'
updated_date: '2026-05-24 18:48'
---
# Constraints: MCU Stock Zephyr Shared Stack

## Stack Ownership
- Active MCU targets are `devices/power/mcu`, `devices/weather/mcu`,
  `devices/unit/mcu`, and `devices/power-si/mcu`.
- Shared stock Zephyr workspace, Python/west environment, caches, and helper recipes belong under `devices/common/mcu/`.
- Shared nRF REDCON source and TXR1 NVE logic remain in
  `devices/common/mcu/xiao_nrf54l15`.
- `power-si` owns its XIAO MG24 OpenThread/CoAP application and TXT1 factory
  data reader under `devices/power-si/mcu`.
- Device-specific behavior remains in local `src/main.c`, `zephyr/prj.conf`, Kconfig, and devicetree overlays.

## Command Rules
- Builds stay device-owned through `just <device>::mcu::build`.
- Shared setup and factory/NVE programming commands use root `mcu` recipes.
- Firmware flashing commands stay device-owned as `<device>::mcu::flash`.
- `mcu::check` is the shared non-flashing preflight for host tools, the stock
  Zephyr workspace, nRF OpenOCD config, XIAO MG24 pyOCD target pack, shared
  board config, and factory-data scripts.
- `<device>::mcu::flash` must use an existing built firmware HEX and must not build implicitly.
- NVE commands are shared factory-data programming surfaces. Existing nRF
  devices use TXR1 at `0x000f0000`; `power-si` uses TXT1 with Thing name and
  Thread dataset TLVs.
- Just recipe arguments remain positional.

## Safety Rules
- Agents must not run firmware or NVE flashing commands.
- Agents may run build and `mcu::check` commands, but must not run `<device>::mcu::flash` or `mcu::nve`.
- Host tools remain manual prerequisites: `git`, `python3`, `cmake`, `ninja`, `dtc`, `arm-none-eabi-gcc`, and `openocd`.
- Repository shell and just code must stay POSIX `sh` compatible.

## Compatibility Rules
- The shared stock Zephyr workspace defaults to `main` for XIAO MG24
  IEEE 802.15.4 support. `TXING_ZEPHYR_VERSION` remains the explicit override
  for a different stock Zephyr revision.
- REDCON protocol, UUIDs, payloads, NVE layout, BLE identity behavior, Thing Shadow schemas, and Sparkplug semantics are unchanged.
- Existing unit/weather BLE TX-power settings should be preserved initially; only change them if physical stock-Zephyr validation shows connection instability, and record the reason.
