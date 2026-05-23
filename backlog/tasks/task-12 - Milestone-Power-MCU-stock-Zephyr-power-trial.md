---
id: TASK-12
title: 'Milestone: Power MCU stock Zephyr power trial'
status: Done
assignee: []
created_date: '2026-05-23 19:24'
updated_date: '2026-05-23 22:13'
labels: []
milestone: Power MCU stock Zephyr power trial
dependencies: []
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
ordinal: 17000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Power MCU stock Zephyr trial is split into ordered implementation, baseline measurement, and power-reduction tasks.
- [x] #2 Each child task requires successful power MCU compilation before completion.
- [x] #3 Scope remains limited to the power device type and preserves manual OpenOCD flashing.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-05-24 milestone closeout: TASK-12.1, TASK-12.2, and TASK-12.3 are all Done. The trial produced a stock Zephyr v4.4.0 power MCU build flow, recorded baseline measurements, and performed one low-risk power customization experiment. Direct OpenOCD flash/NVE command surfaces were preserved and no automatic flashing was performed by the agent. Final retained firmware follows upstream stock-Zephyr GRTC keep-alive behavior, uses controller TX 0 dBm with advertising TX +4 dBm, and keeps REDCON protocol/NVE behavior unchanged. Manual measurements on the known-good board remained about 0.06 mA advertising/disconnected idle and about 0.10 mA connected idle; temporary NCS/SoftDevice comparison was about 0.08 mA connected idle, so next direction needs team decision outside this milestone.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Closed the Power MCU stock Zephyr power trial milestone. Completed ordered child tasks for stock-Zephyr build support, baseline flash/measurement, and a best-effort power reduction pass. The retained source keeps stock Zephyr defaults for the nRF GRTC keep-alive path because the keep_alive=n experiment was stable but did not improve measured connected idle current. The final evidence shows the power MCU stock Zephyr path is stable with web UI REDCON 4-3-4 switching, preserves manual OpenOCD flashing and NVE generation, and measures about 0.10 mA connected idle on the tested board, compared with about 0.08 mA for the temporary NCS/SoftDevice comparison. Further direction is deferred for team review.
<!-- SECTION:FINAL_SUMMARY:END -->
