---
id: TASK-16
title: 'Milestone: MCU NCS cleanup'
status: Done
assignee:
  - '@Codex'
updated_date: '2026-05-24 18:41'
created_date: '2026-05-24 13:22'
labels: []
milestone: MCU NCS cleanup
dependencies:
  - TASK-15
references:
  - devices/common/mcu
  - devices/power/mcu
  - devices/weather/mcu
  - devices/unit/mcu
  - .gitmodules
documentation:
  - >-
    backlog/docs/architecture/mcu-stock-zephyr-shared-stack/doc-6 -
    MCU-stock-Zephyr-shared-stack-migration.md
  - >-
    backlog/docs/constraints/mcu-stock-zephyr-shared-stack/doc-7 -
    Constraints-MCU-stock-Zephyr-shared-stack.md
  - >-
    backlog/docs/milestones/mcu-ncs-cleanup/doc-11 -
    Milestone-MCU-NCS-cleanup.md
  - docs/components/mcu.md
ordinal: 24000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Obsolete active NCS build paths, per-device NCS wrappers, and generated NCS workspace docs are removed or retired.
- [x] #2 The modules/nrfconnect/sdk-nrf submodule and its .gitmodules entry are removed after all active MCU targets build on stock Zephyr.
- [x] #3 MCU component docs, device MCU READMEs, and agent guidance describe stock Zephyr as the active MCU stack.
- [x] #4 power, weather, and unit MCU builds pass on the shared stock Zephyr stack after cleanup.
- [x] #5 Source and documentation searches show no active NCS command path remains for active MCU builds.
- [x] #6 Device-specific MCU directories no longer contain obsolete generated NCS, per-device Zephyr workspace, build, venv, pip, Zephyr, ccache, or Python cache folders.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Remove obsolete shared NCS helper files, generated NCS workspace docs, generated NCS workspace contents, and the `modules/nrfconnect/sdk-nrf` submodule/.gitmodules entry.
2. Update active MCU docs, device MCU READMEs, agent guidance, and milestone guidance to describe stock Zephyr and the simplified MCU command surface.
3. Verify the active command surface and stale-reference searches show no active NCS command path remains.
4. Validate `just mcu::check` and all active MCU builds without running firmware or NVE flashing commands.
5. Record validation evidence and close the task only when all acceptance criteria are proven.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Removed the obsolete shared NCS build surface: deleted `.gitmodules`, `modules/nrfconnect/sdk-nrf`, `devices/common/mcu/scripts/ncs_mcu.py`, and the generated `devices/common/mcu/ncs` workspace/docs. Removed obsolete per-device generated-cache ignore patterns from `devices/unit/mcu/.gitignore`. Updated root agent routing plus MCU milestone/architecture/constraint guidance so active MCU documentation describes stock Zephyr and the simplified command surface: root `mcu::install`, `mcu::check`, `mcu::flash <device-type>`, `mcu::nve <thing-name>`, and device-owned `<device>::mcu::build` / `clean`.

Validation passed on 2026-05-24: `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `just mcu::check`, `just power::mcu::build`, `just weather::mcu::build`, and `just unit::mcu::build`. Recipe listings show root MCU exposes only install/check/flash/nve and each active device MCU exposes only build/clean. Active source/doc search over `AGENTS.md`, `docs`, and `devices` returned no NCS or removed command-path references outside the stock Zephyr workspace. Directory audit confirmed `.gitmodules`, `modules/nrfconnect/sdk-nrf`, `devices/common/mcu/ncs`, and `devices/common/mcu/scripts/ncs_mcu.py` are absent, and no device-specific MCU directory contains obsolete `.zephyr-workspace`, `.venv`, `.pip-cache`, `.zephyr-cache`, `.ccache`, `__pycache__`, `ncs`, or `sdk-nrf` folders. No firmware or NVE flashing command was run.
<!-- SECTION:NOTES:END -->
