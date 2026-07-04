---
id: TASK-23.3
title: rig cost posture is documented and measured
status: To Do
assignee: []
created_date: '2026-07-04 16:30'
labels: []
milestone: m-2
dependencies:
  - TASK-23.1
  - TASK-23.2
references:
  - docs/components/rig.md
  - docs/sparkplug-lifecycle.md
documentation:
  - >-
    backlog/docs/architecture/rig-idle-cost-parity/doc-25 -
    Rig-REDCON-1-idle-cost-parity-architecture.md
parent_task_id: TASK-23
priority: medium
ordinal: 60000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Document the cost posture (REDCON 1 as the affordable resting state, what drives cost per rig type, the 300-second inventory expectation, restart as force-refresh, and the recommendation of an AWS Budgets guardrail) and record the before/after measurement evidence for the milestone targets.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Operator documentation states the idle-awake cost model, the refresh cadence and force-refresh options, and the budget guardrail recommendation.
- [ ] #2 Measured before/after operation counts extrapolated to monthly cost are recorded as milestone evidence and meet the targets in the architecture doc.
<!-- AC:END -->
