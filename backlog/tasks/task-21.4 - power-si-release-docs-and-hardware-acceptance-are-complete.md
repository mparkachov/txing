---
id: TASK-21.4
title: power-si release docs and hardware acceptance are complete
status: In Progress
assignee:
  - '@Codex'
created_date: '2026-06-20 07:12'
updated_date: '2026-06-20 16:29'
labels: []
milestone: m-0
dependencies:
  - TASK-21.1
  - TASK-21.2
  - TASK-21.3
references:
  - rig/docs
  - docs/installation.md
  - docs/components/rig.md
documentation:
  - >-
    backlog/docs/milestones/power-si-thread-device/doc-22 -
    Milestone-power-si-Thread-device-type.md
parent_task_id: TASK-21
priority: medium
ordinal: 48000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make the power-si Thread runtime operationally usable by packaging the new rig daemon, documenting OTBR and provisioning prerequisites, and recording manual hardware acceptance evidence.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Rig build, release, mise/service, and installation documentation include txing-thread-connectivity as the third daemon without changing existing BLE/Sparkplug service semantics.
- [x] #2 Documentation explains external OTBR prerequisites, power-si factory provisioning, manual firmware/factory flashing commands, and the rule that real Thread dataset TLVs are never committed.
- [x] #3 Automated validation results are recorded for MCU, rig Go, shared AWS/Python, and Office tests relevant to power-si.
- [ ] #4 Manual acceptance evidence covers user-run factory provisioning, firmware flashing, SRP registration, rig discovery, REDCON 4/3 transitions, D1 output, battery shadow updates, and Sparkplug birth/data/death behavior.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect existing rig, MCU, shared AWS, and Office docs/tests to identify what TASK-21.4 must add beyond the implementation tasks.
2. Update durable docs for txing-thread-connectivity release/service coverage, OTBR prerequisites, power-si factory provisioning, manual flashing, dataset secrecy, and hardware acceptance evidence capture.
3. Run the relevant MCU, rig Go, shared AWS/Python, and Office validation commands that can run without hardware/AWS mutation.
4. Record validation and manual-acceptance status in Backlog, marking only criteria proven by current evidence.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
- Expanded `devices/power-si/README.md` from the initial contract stub into the operator-facing procedure for rig prerequisites, external OTBR expectations, TXT1 factory data, dataset TLV secrecy, firmware build, manual firmware/factory flashing command shapes, and hardware acceptance evidence capture.
- Updated `docs/installation.md` so the raspi rig setup path explicitly covers BLE and Thread-managed devices, keeps OTBR installation external, and points `power-si` operators to the device provisioning/flashing guide.
- Fixed `docs/artifacts.md` so the rig asset list includes `txing-thread-connectivity-linux-aarch64.tar.gz` alongside the existing Sparkplug and BLE daemon assets.
- Manual hardware acceptance is still pending. No hardware flashing/programming, OTBR discovery, SRP registration, REDCON transitions, D1 measurement, battery shadow observation, or Sparkplug birth/data/death hardware evidence was run or available in this session.
<!-- SECTION:NOTES:END -->

## Validation

<!-- SECTION:VALIDATION:BEGIN -->
Passed:

- `python3 -m unittest discover -s devices/common/mcu/xiao_mg24/tests`
- `python3 -m unittest discover -s devices/common/mcu/xiao_nrf54l15/tests`
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py devices/common/mcu/xiao_mg24/scripts/thread_factory.py devices/common/mcu/xiao_nrf54l15/scripts/redcon_nve.py`
- `python3 devices/common/mcu/scripts/stock_zephyr_mcu.py check`
- `python3 devices/common/mcu/xiao_mg24/scripts/thread_factory.py validate power-si-001 --dataset-tlvs tmp/power-si-test-dataset.hex`
- `python3 devices/common/mcu/scripts/stock_zephyr_mcu.py --device power-si thread-factory-hex power-si-001 tmp/power-si-test-dataset.hex --output tmp/power-si-thread-factory-test.hex`
- `python3 devices/common/mcu/scripts/stock_zephyr_mcu.py --device power-si build`
- `python3 devices/common/mcu/scripts/stock_zephyr_mcu.py --device power build`
- `go test ./...` from `rig/`
- `just --justfile rig/justfile build`
- `UV_CACHE_DIR=/Users/Maxim/Developer/txing/tmp/uv-cache uv run --project shared/aws/python pytest shared/aws/python/tests`
- `bun test` from `office/`
- `bun run build` from `office/`
- `git diff --check`

The initial direct `python3 -m unittest discover -s shared/aws/python/tests` command failed because it bypassed the uv-managed package import path; the uv/pytest command above is the correct shared AWS validation harness and passed with 137 tests.
<!-- SECTION:VALIDATION:END -->
