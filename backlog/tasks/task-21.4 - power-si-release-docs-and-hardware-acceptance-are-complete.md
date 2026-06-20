---
id: TASK-21.4
title: power-si release docs and hardware acceptance are complete
status: To Do
assignee: []
created_date: '2026-06-20 07:12'
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
- [ ] #1 Rig build, release, mise/service, and installation documentation include txing-thread-connectivity as the third daemon without changing existing BLE/Sparkplug service semantics.
- [ ] #2 Documentation explains external OTBR prerequisites, power-si factory provisioning, manual firmware/factory flashing commands, and the rule that real Thread dataset TLVs are never committed.
- [ ] #3 Automated validation results are recorded for MCU, rig Go, shared AWS/Python, and Office tests relevant to power-si.
- [ ] #4 Manual acceptance evidence covers user-run factory provisioning, firmware flashing, SRP registration, rig discovery, REDCON 4/3 transitions, D1 output, battery shadow updates, and Sparkplug birth/data/death behavior.
<!-- AC:END -->
