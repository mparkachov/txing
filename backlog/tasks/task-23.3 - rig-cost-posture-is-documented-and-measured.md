---
id: TASK-23.3
title: rig cost posture is documented and measured
status: Done
assignee:
  - '@codex'
created_date: '2026-07-04 16:30'
updated_date: '2026-07-06 10:44'
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
- [x] #1 Operator documentation states the idle-awake cost model, the refresh cadence and force-refresh options, and the budget guardrail recommendation.
- [x] #2 Measured before/after operation counts extrapolated to monthly cost are recorded as milestone evidence and meet the targets in the architecture doc.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Derive the TASK-23.3 requirements from the task, dependency evidence, and rig idle-cost architecture targets.
2. Add operator-facing cost posture documentation: REDCON 1 as the affordable resting state, per-rig cost drivers, 300-second standalone inventory cadence, restart/REDCON 4-to-1 force refresh, and AWS Budgets guardrail recommendation.
3. Record milestone measurement evidence with before/after operation counts, monthly extrapolations, and target comparisons for raspi/local and cloud rigs.
4. Add or update focused documentation tests where existing test seams cover the docs.
5. Run focused validation and close TASK-23.3 only if both ACs are directly evidenced.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented TASK-23.3 as documentation and milestone evidence.

Operator documentation: docs/components/rig.md now has a Cost Posture section that states REDCON 1 is the normal affordable idle-awake state, explains standalone raspi/local cost drivers, cloud rig cost drivers, the 300-second inventory cadence, restart and NCMD redcon=4 -> 1 force-refresh options, and the AWS Budgets monthly cost alert recommendation. docs/sparkplug-lifecycle.md now records that REDCON 1 is the expected affordable idle-awake rig posture while REDCON 4 remains deep sleep or maintenance, not the normal cost-control state.

Milestone evidence: backlog/docs/milestones/rig-idle-cost-parity/doc-26 now records measured before/after counts and 30-day monthly extrapolations. Raspi/local evidence uses the 2026-07-06 counted soak: searchIndex=2/3/4/5, describeThing=1, ssmReads=13, devices=4, including across REDCON 1 -> 4 -> 1; extrapolated after state is 8,640 SearchIndex calls/month, about $0.04/month, with no recurring unchanged-refresh DescribeThing or info-log ingestion, meeting the <= ~$0.10/month target. Cloud evidence uses the 2026-07-06 live soak: once-per-minute cloud-mcu invocations and no recurring unchanged shadow updates for cloud-mcu-ph4p98; extrapolated after state is 43,200 ticks/device/month with 0 recurring unchanged UpdateThingShadow, DBIRTH/DDATA, IoT rule, witness invocation, and sparkplug-shadow projection after stable birth, meeting the <= ~$0.50/month/device target.

Validation: python -m unittest shared.aws.python.tests.test_versioning; git diff --check.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-23.3 completed. Operator docs now state the idle-awake cost model, 300-second refresh cadence, force-refresh options, and AWS Budgets guardrail. The milestone doc records before/after measured operation counts and monthly extrapolations for raspi/local and cloud rigs, both meeting the architecture cost targets.
<!-- SECTION:FINAL_SUMMARY:END -->
