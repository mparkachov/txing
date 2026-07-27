---
id: TASK-21.8
title: power-si sed-current reuses the sed-debug functional overlay
status: Done
assignee:
  - '@Codex'
created_date: '2026-07-20 01:26'
updated_date: '2026-07-20 19:21'
labels: []
dependencies:
  - TASK-21.7
documentation:
  - devices/power-si/README.md
  - docs/components/mcu.md
modified_files:
  - devices/common/mcu/scripts/stock_zephyr_mcu.py
  - devices/common/mcu/tests/test_power_si_sed_config.py
  - devices/common/mcu/tests/test_stock_zephyr_mcu.py
  - devices/power-si/mcu/justfile
  - devices/power-si/mcu/zephyr/sed-current.conf
  - devices/power-si/README.md
  - docs/components/mcu.md
parent_task_id: TASK-21
priority: high
type: bug
ordinal: 50500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make sed-current consume the same sed-debug.conf functional overlay as sed-debug. The silent overlay may only disable observability and diagnostics; it must not duplicate or replace the receiver-on SRP bootstrap, SED transition/recovery, REDCON 3/4 rn/n policy, PM/tickless configuration, or isolated RadioAES candidate. This corrects the rejected attempt to restore the retired current profile. Hardware acceptance remains pending: a freshly flashed sed-current image must register SRP and settle to n without serial output.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 sed-current loads sed-debug.conf and preserves its receiver-on SRP bootstrap, SED recovery, REDCON rn/n policy, PM/tickless settings, and isolated radio candidate.
- [x] #2 The sed-current final overlay disables console, shell, UART logging, OpenThread diagnostics, and application diagnostics without duplicating functional SED settings.
- [x] #3 A pristine sed-current build produces the expected XIAO MG24 artifact and static checks verify the overlay order.
- [x] #4 After an operator flashes the fresh sed-current artifact, the device registers a non-deleted SRP service and settles with child R=0 when REDCON is 4.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Keep sed-current as the silent derivative of sed-debug, loading sed-debug.conf before the silent observability overlay.
2. Keep static tests that prevent sed-current from drifting from the sed-debug functional overlay.
3. Build the resulting images and provide the non-serial SRP/child-state acceptance check.
4. Keep hardware acceptance open until a freshly flashed sed-current image registers a non-deleted SRP service and settles with child R=0 at REDCON 4.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
sed-current is the silent derivative of sed-debug. It loads sed-debug.conf first, preserving receiver-on SRP bootstrap, SED recovery, REDCON 3/4 rn/n policy, PM, tickless idle, and the isolated RadioAES candidate; the final overlay disables only observability.

Validation: pristine sed-current and sed-debug builds produced the XIAO MG24 artifacts. Focused static checks verify the overlay order and that sed-current disables console, shell, UART logging, OpenThread diagnostics, and application diagnostics.

Diagnostic outcome (2026-07-20): temporary PM/RAIL/ACK instrumentation verified functional SRP and a child with R=0. A five-second aggregate window was dominated by EM2, but transient HF-clock-preservation requests and radio activity had no identifiable causal owner. TXACK_BLOCKED did not occur. The diagnostic profile and four isolated diagnostic patches were removed because the experiment did not justify a production code change.

Power outcome: all earlier current numbers were invalid because the meter was in AC-current mode. Valid DC observations are approximately 16-20 mA in both SED n and receiver-on rn. No low-current acceptance claim or electrical root cause is recorded.

Hardware acceptance remains open: a freshly flashed sed-current image must register a non-deleted SRP service and settle with child R=0 at REDCON 4.

Final hardware acceptance (2026-07-20): the operator flashed the committed sed-current artifact and confirmed the provisioned device registered its SRP service as deleted:false on port 5683, attached at REDCON 4 as a sleepy child with R=0, switched successfully to REDCON 3/receiver-on mode, and returned successfully to REDCON 4/SED mode.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
sed-current is validated as the silent derivative of sed-debug. Static and build checks passed, and operator hardware evidence confirmed active SRP registration, R=0 at REDCON 4, and working REDCON 4 -> 3 -> 4 link-mode transitions.
<!-- SECTION:FINAL_SUMMARY:END -->
