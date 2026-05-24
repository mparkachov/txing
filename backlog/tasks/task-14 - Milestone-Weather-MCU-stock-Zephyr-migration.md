---
id: TASK-14
title: 'Milestone: Weather MCU stock Zephyr migration'
status: Done
assignee:
  - '@Codex'
created_date: '2026-05-24 13:21'
updated_date: '2026-05-24 17:41'
labels: []
milestone: Weather MCU stock Zephyr migration
dependencies:
  - TASK-13
references:
  - devices/common/mcu
  - devices/weather/mcu
  - devices/weather/mcu/README.md
documentation:
  - >-
    backlog/docs/architecture/mcu-stock-zephyr-shared-stack/doc-6 -
    MCU-stock-Zephyr-shared-stack-migration.md
  - >-
    backlog/docs/constraints/mcu-stock-zephyr-shared-stack/doc-7 -
    Constraints-MCU-stock-Zephyr-shared-stack.md
  - >-
    backlog/docs/milestones/weather-mcu-stock-zephyr-migration/doc-9 -
    Milestone-Weather-MCU-stock-Zephyr-migration.md
ordinal: 22000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 weather::mcu check/build/paths/clean use the shared stock Zephyr stack and no active weather build path depends on NCS.
- [x] #2 Stock-incompatible NCS-only configuration is removed while preserving weather REDCON 4, BME280, battery, D1 power, and NVE behavior.
- [x] #3 check-flash weather and check-nve weather-test print direct OpenOCD commands without programming hardware.
- [x] #4 User manual validation after flashing confirms BLE identity, REDCON service, weather measurement, and battery measurement behavior.
- [x] #5 Obsolete weather MCU generated build/cache/workspace folders and any weather-specific NCS wrapper are removed once the shared stock Zephyr build is validated.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Rewire devices/weather/mcu/justfile to delegate install/check/build/paths/clean and compatibility flash/NVE wrappers to devices/common/mcu/scripts/stock_zephyr_mcu.py.\n2. Remove stock-incompatible NCS-only weather Kconfig and update weather README to the shared stock Zephyr command surface.\n3. Remove obsolete ignored weather generated build/cache/workspace output before validation so the new shared-stack build starts clean.\n4. Validate weather check/build, root mcu check-flash weather, and root mcu check-nve weather-test without running hardware flashing commands.\n5. Record validation evidence and close TASK-14 only if acceptance criteria are satisfied or explicitly note manual physical validation remaining.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Migrated weather MCU recipes to the shared stock Zephyr v4.4.0 helper in devices/common/mcu/scripts/stock_zephyr_mcu.py. Removed CONFIG_NCS_BOOT_BANNER=n from weather prj.conf while preserving REDCON 4-only mask, BME280 measurement enablement, NVE address, BME280 D1 power settle time, and advertising TX +4 dBm. Removed obsolete ignored weather build outputs before building; after validation only the new ignored stock-Zephyr build tree remains. Removed the obsolete per-device OpenOCD support file and empty leftover app/scripts/tests/support folders. Validation passed: just weather::mcu::paths, just weather::mcu::build, just weather::mcu::check, just mcu::check-flash weather, and just mcu::check-nve weather-test. Generated config evidence initially used controller TX -20 dBm. User confirmed manual weather firmware and NVE flashing succeeded, but observed a rig/UI issue where powering on weather could show physically-off power as connected. Rig BLE connectivity was patched to reject stale cached advertisements before publishing alive samples and to scope scan freshness holds to device-specific connect attempts. A follow-up deployment showed weather birth/death flapping while powered on; the scan freshness hold was then moved to the device connect acquisition path so it no longer depends on bluetooth StopScan succeeding and no longer applies across unrelated devices. Follow-up log tuning moved expected background advertisement-connect failures to debug: missing/stale advertisements for powered-off devices and GATT discovery timeouts while fresh advertisements still prove presence are no longer warning-level events; periodic inventory reconciliation also moved from info to debug. Command-path failures remain visible through command results. Current validation on 2026-05-24 passed: just weather::mcu::paths, just weather::mcu::build, just weather::mcu::check, just mcu::check-flash weather, just mcu::check-nve weather-test, and GOCACHE=/Users/Maxim/Developer/txing/tmp/go-build GOPATH=/Users/Maxim/Developer/txing/tmp/go-path TMPDIR=/Users/Maxim/Developer/txing/tmp/go-tmp just --justfile rig/justfile test. User reconfirmed manual weather firmware and NVE flashing worked. User confirmed physical validation for AC #4: device is up and shows correct REDCON and readings. Later stability-first policy changed all XIAO nRF54L15 stock-Zephyr targets to the shared board-level controller TX +4 dBm default in devices/common/mcu/xiao_nrf54l15/board.conf; weather rebuilt successfully with CONFIG_BT_CTLR_TX_PWR_PLUS_4=y and CONFIG_BT_CTLR_TX_PWR_DBM=4 while preserving the weather REDCON and measurement settings.
<!-- SECTION:NOTES:END -->

## Physical Validation

<!-- SECTION:VALIDATION:BEGIN -->
User confirmed the flashed weather device is up and shows correct REDCON and readings after weather firmware/NVE flashing and latest rig deployment.
<!-- SECTION:VALIDATION:END -->
