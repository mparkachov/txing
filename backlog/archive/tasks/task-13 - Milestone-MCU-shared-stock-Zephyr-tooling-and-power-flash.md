---
id: TASK-13
title: 'Milestone: MCU shared stock Zephyr tooling and power flash'
status: Done
assignee:
  - '@Codex'
created_date: '2026-05-24 13:21'
updated_date: '2026-05-24 13:37'
labels: []
milestone: MCU shared stock Zephyr tooling and power flash
dependencies: []
references:
  - devices/common/mcu
  - devices/power/mcu
  - devices/power/README.md
documentation:
  - >-
    backlog/docs/architecture/mcu-stock-zephyr-shared-stack/doc-6 -
    MCU-stock-Zephyr-shared-stack-migration.md
  - >-
    backlog/docs/constraints/mcu-stock-zephyr-shared-stack/doc-7 -
    Constraints-MCU-stock-Zephyr-shared-stack.md
  - >-
    backlog/docs/milestones/mcu-shared-stock-zephyr-tooling-and-power-flash/doc-8
    - Milestone-MCU-shared-stock-Zephyr-tooling-and-power-flash.md
ordinal: 21000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Shared stock Zephyr v4.4.0 install state is initialized under devices/common/mcu and is used by power MCU builds.
- [x] #2 Root mcu just recipes expose install, paths, check-flash, flash, check-nve, and nve command surfaces with positional arguments.
- [x] #3 power::mcu check/build/paths/clean use the shared stock Zephyr stack without depending on a per-device Zephyr workspace.
- [x] #4 check-flash power and check-nve power-test print direct OpenOCD commands without programming hardware.
- [x] #5 Power REDCON behavior, NVE format, stock board target, and manual flashing semantics remain unchanged.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the existing power stock-Zephyr just recipes and current common MCU layout to preserve TASK-12 behavior while moving setup/hardware command ownership to devices/common/mcu.
2. Add shared stock Zephyr helper tooling and root mcu just routing for install, paths, check-flash, flash, check-nve, and nve with positional arguments.
3. Rewrite power::mcu check/build/paths/clean to call the shared stock Zephyr build path and remove dependency on the per-device .zephyr-workspace.
4. Update scoped docs/ignore files only where needed for the new command surface and generated shared workspace state.
5. Validate just mcu::install, just power::mcu::build, just mcu::check-flash power, and just mcu::check-nve power-test without running firmware/NVE flashing commands.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented shared stock Zephyr tooling under devices/common/mcu with Zephyr v4.4.0 install/build/paths/flash/NVE handling and root mcu just recipes. Converted power::mcu build/check/paths/clean to delegate to the shared helper while keeping legacy power flash/NVE wrappers as compatibility shims. Validation passed: just mcu::install, python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py, just mcu::paths, just power::mcu::paths, just power::mcu::build, just power::mcu::check, just mcu::check-flash power, and just mcu::check-nve power-test. Built firmware: devices/power/mcu/build/zephyr-xiao_nrf54l15_cpuapp/zephyr/zephyr.hex. Generated shared NVE HEX: devices/common/mcu/build/redcon-factory-nve.hex. No mcu::flash or mcu::nve programming commands were run.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Shared stock Zephyr v4.4.0 tooling now lives under devices/common/mcu, root mcu recipes expose install/paths/flash/NVE checks, and power::mcu builds through the shared stack. TASK-13 validation passed through install, power build/check, check-flash power, and check-nve power-test; hardware flashing remains manual.
<!-- SECTION:FINAL_SUMMARY:END -->
