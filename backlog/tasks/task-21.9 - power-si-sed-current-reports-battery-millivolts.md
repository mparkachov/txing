---
id: TASK-21.9
title: power-si sed-current reports battery millivolts
status: Done
assignee:
  - '@Codex'
created_date: '2026-07-20 19:27'
updated_date: '2026-07-20 20:06'
labels: []
dependencies:
  - TASK-21.8
documentation:
  - devices/power-si/README.md
  - docs/components/mcu.md
modified_files:
  - devices/power-si/mcu/src/main.c
  - devices/power-si/mcu/zephyr/Kconfig
  - devices/power-si/mcu/zephyr/boards/xiao_mg24.overlay
  - devices/power-si/mcu/zephyr/dts/bindings/txing-battery-divider.yaml
  - devices/power-si/mcu/zephyr/sed-current.conf
  - devices/common/mcu/tests/test_power_si_sed_config.py
  - devices/power-si/README.md
  - docs/components/mcu.md
parent_task_id: TASK-21
priority: high
type: feature
ordinal: 51500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add on-demand XIAO MG24 battery voltage reporting to the power-si sed-current profile. Use the board battery divider enable and ADC input without adding periodic wakeups or changing the standard, debug, or sed-debug firmware profiles.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 sed-current enables battery sampling on PD4 with active-high PD3 divider enable and applies the XIAO MG24 2:1 divider conversion; other firmware profiles remain unchanged and report null.
- [x] #2 GET state and REDCON responses return an integer batteryMv after a successful sample and retain null on sampling failure.
- [x] #3 The existing rig optional batteryMv path publishes the power shadow without a protocol, schema, or MQTT contract change.
- [x] #4 Focused tests and a pristine sed-current build pass, and documentation includes manual hardware validation.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Model the XIAO MG24 battery divider in the application devicetree overlay and gate battery sampling behind a sed-current-only Kconfig option. 2. Add on-demand PD3-enable/PD4-IADC sampling and expose the result through the existing CoAP state payload. 3. Add focused configuration checks, update battery validation documentation, build sed-current, and leave flashing and physical voltage validation to the operator.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented sed-current-only on-demand battery measurement using active-high PD3 divider enable, PD4 IADC input, and the XIAO MG24 2:1 divider conversion. Successful samples feed the existing batteryMv field; failures and all other profiles retain null. The existing rig optional BatteryMV projection path and contract are unchanged. Validation passed: focused MCU tests (9 tests), rig Thread tests, pristine sed-current build, release-profile regression build, and git diff checks. Hardware validation of an integer batteryMv response remains pending after manual flash, so acceptance criterion #2 stays open.

Initial hardware validation exposed a systematic conversion error: Office reported 3332 mV while a DC multimeter measured 4061 mV at the battery. The implementation was corrected without an empirical scale factor: PD3 settling was raised from 1 ms to 30 ms, and PD4 now uses the calibrated 1.21 V internal IADC reference at ADC_GAIN_1_2 before applying the board 2:1 divider ratio. Local Zephyr driver inspection showed the VDDX reference path retains the HAL default 1210 mV calibration metadata; the internal-reference path avoids that mismatch while retaining headroom for a 4.2 V LiPo. Focused tests and a pristine sed-current build pass with the corrected generated devicetree. Hardware comparison of the corrected image remains pending, so acceptance criterion #2 stays open.

Corrected hardware validation (2026-07-20): after flashing the rebuilt sed-current image, the Office battery value tracked the simultaneous DC multimeter reading approximately. This confirms successful integer batteryMv reporting through the existing CoAP, rig, and power-shadow path.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
sed-current now reports XIAO MG24 battery voltage on demand through the existing batteryMv contract. The final implementation uses the PD3-controlled 2:1 divider, PD4 IADC input, a 30 ms settling interval, and the calibrated 1.21 V internal reference at half gain. Focused tests and pristine builds pass, and operator hardware validation confirmed the Office value approximately matches the DC multimeter reading. Other firmware profiles remain unchanged and report null.
<!-- SECTION:FINAL_SUMMARY:END -->
