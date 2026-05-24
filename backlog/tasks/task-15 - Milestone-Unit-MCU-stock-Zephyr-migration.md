---
id: TASK-15
title: 'Milestone: Unit MCU stock Zephyr migration'
status: Done
assignee:
  - '@Codex'
updated_date: '2026-05-24 18:33'
created_date: '2026-05-24 13:21'
labels: []
milestone: Unit MCU stock Zephyr migration
dependencies:
  - TASK-14
references:
  - devices/common/mcu
  - devices/unit/mcu
  - devices/unit/aws/ble-shadow.schema.json
  - devices/unit/aws/power-shadow.schema.json
documentation:
  - >-
    backlog/docs/architecture/mcu-stock-zephyr-shared-stack/doc-6 -
    MCU-stock-Zephyr-shared-stack-migration.md
  - >-
    backlog/docs/constraints/mcu-stock-zephyr-shared-stack/doc-7 -
    Constraints-MCU-stock-Zephyr-shared-stack.md
  - >-
    backlog/docs/milestones/unit-mcu-stock-zephyr-migration/doc-10 -
    Milestone-Unit-MCU-stock-Zephyr-migration.md
  - docs/contracts/unit-device-contracts.md
  - devices/unit/docs/device-rig-shadow-spec.md
ordinal: 23000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 unit::mcu build/clean use the shared stock Zephyr stack and no active unit build path depends on NCS.
- [x] #2 Stock-incompatible NCS-only configuration is removed while preserving unit REDCON 1/2/3/4, D1 power, battery, BLE identity, and NVE behavior.
- [x] #3 Rig-facing Sparkplug and named-shadow semantics remain compatible with the current unit contracts.
- [x] #4 Shared mcu::check validates tool/workspace prerequisites, while firmware and NVE hardware writes stay limited to mcu::flash and mcu::nve.
- [x] #5 User manual validation after flashing confirms REDCON transitions through the rig/web workflow as hardware allows.
- [x] #6 Obsolete unit MCU generated build/cache/workspace folders and any unit-specific NCS wrapper are removed once the shared stock Zephyr build is validated.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Rewire devices/unit/mcu/justfile build/clean to devices/common/mcu/scripts/stock_zephyr_mcu.py and keep shared setup/flash/NVE actions on root mcu recipes.
2. Remove stock-incompatible NCS-only unit Kconfig while preserving REDCON 1/2/3/4, D1 power, battery, BLE identity, NVE, and existing BLE TX-power behavior.
3. Remove obsolete ignored unit generated build/cache/workspace output and any unit-specific NCS wrapper once the shared stock-Zephyr build is validated.
4. Validate root mcu check plus unit build without running firmware or NVE flashing.
5. Record validation evidence and leave AC #5 open for user physical REDCON workflow validation unless confirmed.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Migrated unit MCU recipes to the shared stock Zephyr v4.4.0 helper in devices/common/mcu/scripts/stock_zephyr_mcu.py. Removed CONFIG_NCS_BOOT_BANNER=n from unit prj.conf while preserving REDCON command mask 0x1e, preserve-on-disconnect behavior, NVE address 0x000f0000, D1/power hook wiring, battery reporting configuration, and advertising TX +4 dBm. Removed the unit-specific NCS wrapper script and obsolete ignored NCS build tree; after validation only the new ignored stock-Zephyr build tree remains. No rig, schema, Sparkplug, NVE layout, or BLE protocol files were changed, so rig-facing named-shadow and Sparkplug semantics remain on the existing contracts. Validation passed: just unit::mcu::paths, just unit::mcu::build, just unit::mcu::check, just mcu::check-flash unit, and just mcu::check-nve unit-test. Generated config evidence includes CONFIG_BT_LL_SW_SPLIT=y, CONFIG_REDCON_COMMAND_LEVELS_MASK=0x1e, CONFIG_REDCON_PRESERVE_LEVEL_ON_DISCONNECT=y, CONFIG_REDCON_BLE_ADV_TX_POWER_DBM=4, and CONFIG_REDCON_FACTORY_DATA_ADDRESS=0x000f0000. No firmware or NVE flashing was run; physical REDCON workflow validation AC #5 remains for the user.

User flashed the first stock-Zephyr unit image and powered it on. The rig showed unit as BLE connected, but REDCON switching did not take effect; rig log later reported unit-wrd8ti failed with `timeout on DiscoverServices`, which means the rig did not get far enough through GATT service discovery to write the REDCON command characteristic. A temporary unit-only controller TX fallback to 0 dBm built successfully, then the stability-first policy was made board-wide: devices/common/mcu/xiao_nrf54l15/board.conf now sets CONFIG_BT_CTLR_TX_PWR_PLUS_4=y and CONFIG_BT_CTLR_TX_PWR_DYNAMIC_CONTROL=y for every XIAO nRF54L15 target built through the shared stock-Zephyr helper, including future targets. Unit rebuilt successfully with CONFIG_BT_CTLR_TX_PWR_PLUS_4=y and CONFIG_BT_CTLR_TX_PWR_DBM=4, and just unit::mcu::build completed after this change. AC #5 stays open until the user flashes the rebuilt unit firmware and validates REDCON through rig/web.

After flashing the +4 dBm unit firmware, user reported REDCON 1 -> 4 eventually powers down but visible switching/off convergence can take more than 10 seconds. Firmware review showed a valid REDCON 4 write drives D1 off immediately in enter_redcon_idle(), before notification or measurement work, so the long delay is more consistent with the rig command convergence path than with firmware intentionally delaying D1. Updated rig BLE command handling so, after a successful REDCON 4 write and immediate aggregate REDCON 4 sample publication, command success is published without waiting for the follow-up GATT state read. Wakeup commands REDCON 1/2/3 still use the stricter post-write state confirmation. Added TestIdleCommandDoesNotWaitForStateConfirmation and reran GOCACHE=/Users/Maxim/Developer/txing/tmp/go-build GOPATH=/Users/Maxim/Developer/txing/tmp/go-path TMPDIR=/Users/Maxim/Developer/txing/tmp/go-tmp just --justfile rig/justfile test successfully. AC #5 remains open until user redeploys rig and validates REDCON 4 convergence physically.

Follow-up rig review corrected two assumptions that did not match the common XIAO nRF54L15 controller behavior. First, advertisement-only evidence now means only Sparkplug/BLE reachability for power, weather, and unit alike; weather advertisements no longer imply REDCON 4 or valid power/weather capabilities until a GATT state/measurement read or command-applied state confirms them. Second, active BLE connects stop scanner availability globally, so scan freshness is held for all sessions while any connect is active, but only if that device's last advertisement was fresh when the active connect began; the post-connect recent hold remains scoped to the device that connected. Updated rig contract docs and tests, including weather advertisement capability expectations and cross-session scan freshness hold coverage. Validation passed with GOCACHE=/Users/Maxim/Developer/txing/tmp/go-build GOPATH=/Users/Maxim/Developer/txing/tmp/go-path TMPDIR=/Users/Maxim/Developer/txing/tmp/go-tmp just --justfile rig/justfile test.

Simplified the active MCU command surface per user direction. Root `mcu` now exposes only `install`, `check`, `flash <device-type>`, and `nve <thing-name>`; device MCU justfiles expose only device-owned `build` and `clean`. Removed public path, check-flash, check-nve, build-nve-hex, per-device install, per-device flash, and per-device NVE wrapper recipes. `mcu::check` is the non-mutating shared preflight for host tools, stock Zephyr workspace, Seeed OpenOCD config, shared board config, and NVE script. `mcu::nve` remains the command that generates the NVE HEX and flashes it. Active MCU docs and READMEs now document the simplified workflow.

User flashed the unit with the simplified process and confirmed AC #5: the unit responds to REDCON transitions through the web UI.
<!-- SECTION:NOTES:END -->

## Physical Validation

<!-- SECTION:VALIDATION:BEGIN -->
User confirmed the flashed unit responds to REDCON transitions through the web UI after the simplified MCU build/flash/NVE workflow.
<!-- SECTION:VALIDATION:END -->
