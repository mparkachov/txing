# Template MCU

Place firmware/watch-layer code here when the device type has an MCU component.

This directory is only a scaffold and is not an active firmware target. New XIAO
nRF54L15 REDCON firmware targets should follow the shared stack documented in
`../../../docs/components/mcu.md`: compile
`devices/common/mcu/xiao_nrf54l15/src/redcon.c`, include
`devices/common/mcu/xiao_nrf54l15/include`, and route install/check/build
through `devices/common/mcu/scripts/ncs_mcu.py`.
