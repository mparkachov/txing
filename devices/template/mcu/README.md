# Template MCU

Place firmware/watch-layer code here when the device type has an MCU component.

This directory is only a scaffold and is not an active firmware target. New XIAO
nRF54L15 REDCON firmware targets should follow the shared stack documented in
`../../../docs/components/mcu.md`: compile
`devices/common/mcu/xiao_nrf54l15/src/redcon.c`, include
`devices/common/mcu/xiao_nrf54l15/include`, use root `mcu::install` /
`mcu::check` for the shared stack, and route the device-owned build through
`devices/common/mcu/scripts/stock_zephyr_mcu.py`.
