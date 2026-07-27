---
id: TASK-21.7
title: power-si SED current profile isolates debug peripheral power
status: Done
assignee:
  - '@Codex'
created_date: '2026-07-20 01:02'
updated_date: '2026-07-27 20:12'
labels: []
dependencies: []
documentation:
  - devices/power-si/README.md
  - docs/components/mcu.md
modified_files:
  - devices/common/mcu/scripts/stock_zephyr_mcu.py
  - devices/power-si/mcu/justfile
  - devices/power-si/mcu/zephyr/sed-current.conf
  - devices/common/mcu/tests/test_power_si_sed_config.py
  - devices/common/mcu/tests/test_stock_zephyr_mcu.py
  - devices/power-si/README.md
  - docs/components/mcu.md
parent_task_id: TASK-21
priority: high
type: task
ordinal: 49500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create a silent SED current-characterization firmware profile. It must preserve the validated sed-debug SED, bounded recovery, and REDCON 3/4 rn/n link-mode behavior, while disabling serial console, shell, OpenThread diagnostics, UART log output, and other debug instrumentation so those facilities cannot hold the MCU out of deep sleep. Document that prior current readings were invalid because the multimeter was in AC-current mode. Preserve existing task history by appending the correction rather than rewriting earlier evidence.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 sed-current retains the SED poll period, recovery behavior, REDCON link-mode test behavior, and isolated radio candidate used by sed-debug.
- [x] #2 sed-current disables UART console, serial shell, OpenThread shell/debug output, and UART logging in its generated configuration.
- [x] #3 Current documentation states that prior AC-current readings are invalid and gives a DC-current measurement procedure using sed-current.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a distinct stock-Zephyr build/flash profile that retains sed-debug functional Kconfig switches and the isolated radio candidate while omitting debug overlays. 2. Add static profile-contract tests and build the profile to inspect its generated Kconfig. 3. Append the measurement correction and replace current-characterization guidance with an explicit DC-current test procedure.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented silent sed-current build and flash routing. It preserves the sed-debug SED recovery and REDCON rn/n link-mode Kconfig switches plus the isolated RadioAES candidate, but does not load debug.conf. A pristine build completed and produced devices/power-si/mcu/build/zephyr-xiao_mg24-sed-current/zephyr/zephyr.hex. Generated config confirms SED MTD, 5000 ms poll, PM, and tickless kernel are enabled while serial, console, logging, shell, OpenThread debug, SRP PSA diagnostics, and PM-transition diagnostics are disabled. compile_commands.json has no uart_silabs_usart.c, shell_uart.c, uart_console.c, or log_backend_uart sources. Corrected current-measurement docs invalidate all prior AC-current readings and require DC mode.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Created sed-current as the silent counterpart to sed-debug, documented the invalid AC-current history without rewriting it, and verified the profile with source tests plus a pristine XIAO MG24 build.
<!-- SECTION:FINAL_SUMMARY:END -->
