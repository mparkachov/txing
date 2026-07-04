---
id: TASK-23.2
title: cloud rig ticks are change-aware and redcon-paced
status: To Do
assignee: []
created_date: '2026-07-04 16:30'
labels: []
milestone: m-2
dependencies: []
references:
  - devices/cloud-mcu/lambda/internal/cloudmcu/cloudmcu.go
  - docs/sparkplug-lifecycle.md
documentation:
  - >-
    backlog/docs/architecture/rig-idle-cost-parity/doc-25 -
    Rig-REDCON-1-idle-cost-parity-architecture.md
parent_task_id: TASK-23
priority: high
ordinal: 59000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Remove change-blind work from the cloud rig tick chain: sqs and power shadow writes happen only when the rendered reported state changes; device Sparkplug publication happens on change plus at most one liveness DDATA per device per minute; sleeping devices receive one tick per minute while awake (REDCON 3) devices keep the 6-second cadence for ECS reconciliation; per-tick device identity lookups are cached. Any change to the NBIRTH refresh cadence must be explicitly reconciled with the Sparkplug liveness contract rather than made silently.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A sleeping cloud-mcu device causes no shadow writes and at most one Sparkplug publish (with its witness invocation) per minute, verified by unit tests asserting no-write/no-publish on unchanged ticks and by a counted soak.
- [ ] #2 Waking, sleeping, and DCMD command convergence behave exactly as before, including command feedback metrics and ECS task reconciliation at REDCON 3.
- [ ] #3 Witness projections and office views remain unchanged for both sleeping and awake devices.
<!-- AC:END -->
