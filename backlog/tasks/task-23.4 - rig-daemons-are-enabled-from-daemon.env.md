---
id: TASK-23.4
title: rig daemons are enabled from daemon.env
status: To Do
assignee: []
created_date: '2026-07-06 07:19'
labels: []
milestone: m-2
dependencies: []
references:
  - rig/rig-daemon.env.template
  - rig/justfile
  - rig/internal/rigconfig/config.go
  - docs/components/rig.md
documentation:
  - >-
    backlog/docs/architecture/rig-idle-cost-parity/doc-25 -
    Rig-REDCON-1-idle-cost-parity-architecture.md
  - >-
    backlog/docs/milestones/rig-idle-cost-parity/doc-26 -
    Milestone-rig-idle-cost-parity.md
parent_task_id: TASK-23
priority: medium
ordinal: 64000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Rig daemon enablement is explicit, readable, and configured from daemon.env for raspi and local rigs. Operators can keep the default manager-only posture, then enable BLE and/or Thread by editing config and restarting instead of changing service shape or relying on ambiguous flags. BLE no-radio/development behavior remains distinct from whether the BLE connectivity daemon is enabled.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The rendered daemon.env template defaults to sparkplug manager enabled and BLE and Thread connectivity disabled, with clear variable names for each daemon's enablement.
- [ ] #2 The rig start/runtime path honors daemon.env enablement consistently for local and raspi-style rigs, so enabling BLE or Thread requires a config edit plus restart, not a different local-only command shape.
- [ ] #3 BLE no-radio/development mode is named and documented separately from BLE daemon enablement, and existing behavior is either preserved or given an explicit migration path.
- [ ] #4 Rig documentation explains the manager-only default, how to enable BLE and Thread, and how to verify which daemons are expected to run on macOS and raspi rigs.
<!-- AC:END -->
