---
id: TASK-21.11
title: Consolidate power-si final firmware onto the validated SED profile
status: Done
assignee:
  - '@Codex'
created_date: '2026-07-27 19:15'
updated_date: '2026-07-27 19:34'
labels: []
milestone: m-0
dependencies: []
references:
  - devices/common/mcu/scripts/stock_zephyr_mcu.py
  - devices/power-si/mcu/zephyr/sed-debug.conf
  - devices/power-si/mcu/zephyr/release.conf
  - devices/common/mcu/patches/silabs-radioaes-zero-length-ccm.patch
documentation:
  - devices/power-si/README.md
  - docs/components/mcu.md
parent_task_id: TASK-21
priority: high
type: enhancement
ordinal: 53500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make the final power-si release use the validated SED behavior currently shared by sed-debug and sed-current. The RadioAES CCM candidate must apply only during builds and leave upstream intact. sed-debug remains diagnostic; sed-current becomes redundant and is removed.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Release uses the validated SED overlay and isolated RadioAES CCM build-time patch.
- [x] #2 Release is silent and reports batteryMv using the current sed-current path.
- [x] #3 sed-debug behavior remains unchanged.
- [x] #4 sed-current build, flash, tests, and documentation are removed or updated.
- [x] #5 A release build proves the isolated patch is reversed afterward; no agent flashing occurs.
- [x] #6 Manual final-image acceptance confirms Office and LED REDCON 4→3→4.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Promote the validated SED functional overlay and isolated RadioAES CCM build-time patch to the release profile; retain sed-debug; remove sed-current; update tests and docs; build without flashing; then manually verify final REDCON 4→3→4 in Office and LED.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented the power-si-only release override: release now merges sed-debug.conf followed by release.conf, applies the isolated Silabs RadioAES CCM patch only during the build, and restores the HAL checkout afterward. Removed the sed-current profile, build/flash commands, configuration, tests, and product documentation while preserving sed-debug diagnostics. Validation passed: 21 focused pytest tests; release HEX at devices/power-si/mcu/build/zephyr-xiao_mg24/zephyr/zephyr.hex; sed-debug HEX at devices/power-si/mcu/build/zephyr-xiao_mg24-sed-debug/zephyr/zephyr.hex. Both build logs record patch reversal and the Hal checkout is clean. No hardware was flashed by the agent.

Manual final-image acceptance confirmed by the operator: the Office REDCON transition 4→3→4 was reflected by the board LED for each state.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Final power-si release now consolidates the validated SED recovery/link-mode behavior, silent battery reporting, and isolated build-time RadioAES CCM candidate. The obsolete sed-current profile is removed; sed-debug remains diagnostic. Focused tests and both release/sed-debug builds passed, the Silabs HAL checkout was restored cleanly, and manual Office/LED REDCON 4→3→4 acceptance passed.
<!-- SECTION:FINAL_SUMMARY:END -->
