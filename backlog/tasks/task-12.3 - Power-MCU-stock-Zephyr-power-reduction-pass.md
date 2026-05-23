---
id: TASK-12.3
title: Power MCU stock Zephyr power reduction pass
status: Done
assignee:
  - Codex
created_date: '2026-05-23 19:24'
updated_date: '2026-05-23 22:12'
labels: []
milestone: Power MCU stock Zephyr power trial
dependencies:
  - TASK-12.2
references:
  - devices/power/mcu
  - devices/power/README.md
documentation:
  - >-
    backlog/docs/architecture/power-mcu-stock-zephyr-power-trial/doc-4 -
    Power-MCU-stock-Zephyr-power-trial.md
  - >-
    backlog/docs/milestones/power-mcu-stock-zephyr-power-trial/doc-5 -
    Milestone-Power-MCU-stock-Zephyr-power-trial.md
modified_files:
  - devices/power/mcu
  - devices/power/README.md
parent_task_id: TASK-12
ordinal: 20000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Power customizations are made only after Task 2 baseline measurements are recorded.
- [x] #2 REDCON protocol, BLE identity/NVE format, manual OpenOCD flashing commands, and power-device behavior remain unchanged.
- [x] #3 just power::mcu::check, build, check-flash, and check-nve power-test all succeed after customization.
- [x] #4 The user manually flashes and re-measures current after customization.
- [x] #5 Task notes record each power-focused customization and before/after current measurements; success is best-effort reduction, not a fixed numeric threshold.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Confirm TASK-12.2 baseline evidence is recorded before changing power behavior.
2. Review the current power MCU stock-Zephyr config and REDCON/BLE contracts to select only low-risk power-focused customizations that preserve protocol, NVE identity, manual OpenOCD commands, and wake/sleep behavior.
3. Apply the smallest viable stock-Zephyr customization, document what changed and why, and avoid rig changes or automatic flashing.
4. Run `just power::mcu::check`, `build`, `check-flash`, and `check-nve power-test`; verify generated config and command surface.
5. Record before/after measurement expectations and leave/close the task according to available manual measurement evidence.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-05-23 stock-Zephyr retest result: after reverting the temporary NCS/SoftDevice comparison experiment and rebuilding/flashing the current branch stock Zephyr firmware, the user measured connected REDCON idle back at about 0.10 mA. This matches the TASK-12.2 stock baseline. No power-reduction customization is retained yet; current branch remains the stock-Zephyr path at 0 dBm for the next TASK-12.3 investigation step.

2026-05-23 TASK-12.3 customization: retained a stock-Zephyr-only app Kconfig default in devices/power/mcu/zephyr/Kconfig: CONFIG_NRF_GRTC_TIMER_AUTO_KEEP_ALIVE defaults to n, so the nRF GRTC SYSCOUNTER is allowed to use Zephyr's managed lower-power state between REDCON/BLE events instead of being kept alive while any core is active. A direct prj.conf assignment was rejected by Zephyr because the symbol is hidden; that invalid attempt was not retained. Generated config evidence after rebuild: CONFIG_NRF_GRTC_TIMER_AUTO_KEEP_ALIVE is absent from .config/autoconf.h, CONFIG_NRF_GRTC_START_SYSCOUNTER remains y, controller TX remains 0 dBm with CONFIG_BT_CTLR_TX_PWR_0=y and CONFIG_BT_CTLR_TX_PWR_DBM=0, advertising TX remains CONFIG_REDCON_BLE_ADV_TX_POWER_DBM=4, and connection parameters remain interval 100 ms, latency 0, supervision 20000 ms. Local validation after customization: just power::mcu::check passed, just power::mcu::build passed with FLASH 112200 B and RAM 20107 B, just power::mcu::check-flash printed the same OpenOCD zephyr.hex programming command surface, and just power::mcu::check-nve power-test wrote redcon-factory-nve.hex at 0x000f0000 with deviceName power-test and printed the NVE OpenOCD command. Before measurements remain the TASK-12.2 baseline: about 0.06 mA advertising/disconnected idle and about 0.10 mA connected idle on stock Zephyr, with a temporary NCS/SoftDevice comparison at about 0.08 mA connected idle. After-flash current and manual REDCON behavior validation are still pending user measurement.

2026-05-24 manual post-customization result: user manually flashed the customized stock-Zephyr build, switched REDCON in both directions several times from the web UI, and reported stable behavior. Connected idle current remained about 0.10 mA, the same as the stock-Zephyr baseline. This means the GRTC auto-keep-alive customization is behavior-compatible but did not produce a measurable connected-idle reduction on the tested board/rig setup.

2026-05-24 retention decision: after rechecking the pinned Zephyr v4.4.0 source, NRF_GRTC_TIMER_AUTO_KEEP_ALIVE is a hidden timer-driver symbol that upstream defaults to y when NRF_GRTC_START_SYSCOUNTER is enabled. The measured n experiment was stable but did not reduce connected idle current, so the app-level configdefault override was removed and the power MCU now follows the upstream keep-alive=y default again. Post-revert validation: just power::mcu::check passed with FLASH 112200 B and RAM 20107 B; generated config shows CONFIG_NRF_GRTC_TIMER_AUTO_KEEP_ALIVE=y, CONFIG_NRF_GRTC_START_SYSCOUNTER=y, controller TX remains 0 dBm, advertising TX remains +4 dBm, and REDCON connection parameters remain interval 100 ms, latency 0, supervision 20000 ms. check-flash and check-nve power-test still print the expected OpenOCD command surfaces.

2026-05-24 final retained-build flash result: user manually flashed the current retained build after removing the GRTC auto-keep-alive override, confirmed web UI REDCON 4-3-4 switching remains stable across several tries, and reported no measurement change. The retained firmware therefore follows upstream keep-alive=y and preserves the measured stock-Zephyr connected idle behavior at about 0.10 mA.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed the TASK-12.3 stock-Zephyr power reduction pass as a best-effort measurement experiment. Tested a stock-Zephyr-only GRTC power customization by defaulting CONFIG_NRF_GRTC_TIMER_AUTO_KEEP_ALIVE to n through app Kconfig; local gates passed and user manually flashed it, but connected idle remained about 0.10 mA while web UI REDCON switching stayed stable. After rechecking Zephyr's pinned defaults, the no-benefit hidden-symbol override was removed, so the retained firmware follows upstream keep-alive=y behavior. User manually flashed the retained build, confirmed REDCON 4-3-4 switching remained stable, and observed no measurement change. Current generated config keeps REDCON protocol settings, BLE identity/NVE command surface, controller TX at 0 dBm, advertising TX at +4 dBm, connection interval 100 ms, latency 0, and supervision 20000 ms. The experiment is recorded, behavior compatibility was validated, and no measured stock-Zephyr connected-idle reduction was found.
<!-- SECTION:FINAL_SUMMARY:END -->
