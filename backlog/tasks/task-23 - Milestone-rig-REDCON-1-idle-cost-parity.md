---
id: TASK-23
title: 'Milestone: rig REDCON 1 idle cost parity'
status: To Do
assignee: []
created_date: '2026-07-04 16:30'
labels: []
milestone: m-2
dependencies: []
references:
  - rig/internal/registry/registry.go
  - devices/cloud-mcu/lambda/internal/cloudmcu/cloudmcu.go
  - docs/sparkplug-lifecycle.md
documentation:
  - >-
    backlog/docs/architecture/rig-idle-cost-parity/doc-25 -
    Rig-REDCON-1-idle-cost-parity-architecture.md
  - >-
    backlog/docs/milestones/rig-idle-cost-parity/doc-26 -
    Milestone-rig-idle-cost-parity.md
priority: high
ordinal: 57000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make REDCON 1 the affordable resting posture for all rig types: while no managed device is awake, recurring AWS cost stays close to REDCON 4 (raspi/local <= ~$0.10/month; cloud <= ~$0.50/month per sleeping device). Achieved by removing change-blind shadow operations and per-tick churn in the cloud rig and by slowing/caching the raspi-local inventory loop (300 s accepted by business; rig restart forces refresh). REDCON semantics, command latency, and witness ownership are unchanged. Implementation must proceed through child tasks.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Idle-awake recurring AWS operations are reduced to the targets in the architecture doc, evidenced by a counted before/after soak.
- [ ] #2 REDCON command convergence latency, lifecycle projections, and office behavior are unchanged.
- [ ] #3 The cost posture and force-refresh behavior are documented for operators.
<!-- AC:END -->
