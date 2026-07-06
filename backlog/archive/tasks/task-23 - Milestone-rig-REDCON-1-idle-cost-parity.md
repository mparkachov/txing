---
id: TASK-23
title: 'Milestone: rig REDCON 1 idle cost parity'
status: Done
assignee:
  - '@codex'
created_date: '2026-07-04 16:30'
updated_date: '2026-07-06 10:51'
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
- [x] #1 Idle-awake recurring AWS operations are reduced to the targets in the architecture doc, evidenced by a counted before/after soak.
- [x] #2 REDCON command convergence latency, lifecycle projections, and office behavior are unchanged.
- [x] #3 The cost posture and force-refresh behavior are documented for operators.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Closure audit completed on 2026-07-06.

Child state: TASK-23.1, TASK-23.2, TASK-23.3, and TASK-23.4 are all Done. The milestone doc now lists all four implementation tasks, including the later daemon.env enablement child.

AC #1 evidence: counted before/after evidence is recorded in the milestone doc. Raspi/local live soak showed unchanged refresh counters searchIndex=2/3/4/5 while describeThing stayed 1 and ssmReads stayed 13, including across REDCON 1 -> 4 -> 1. The after-state extrapolation is 8,640 SearchIndex calls/month, about $0.04/month, with no recurring unchanged-refresh DescribeThing or info-log ingestion, meeting the <= ~$0.10/month target. Cloud live soak showed once-per-minute cloud-mcu invocations and no recurring unchanged shadow updates for cloud-mcu-ph4p98; after-state extrapolation is 43,200 ticks/device/month with 0 recurring unchanged UpdateThingShadow, DBIRTH/DDATA, IoT rule, witness invocation, and sparkplug-shadow projection after stable birth, meeting the <= ~$0.50/month/device target.

AC #2 evidence: TASK-23.2 validation covered DCMD command convergence, REDCON 3 ECS reconciliation, witness projections, and office views. TASK-23.1 kept standalone REDCON 4 -> 1 immediate refresh covered by unit tests and a live REDCON 1 -> 4 -> 1 transition in the counted soak. TASK-23.4 only made daemon enablement explicit from daemon.env and kept Sparkplug lifecycle semantics unchanged. Caveat: TASK-23.1 AC #2 new-device timing was intentionally not live-tested per user direction on 2026-07-06; this remains recorded in TASK-23.1 and is not treated as a blocker for this parent closure.

AC #3 evidence: docs/components/rig.md documents REDCON 1 as the affordable idle-awake posture, raspi/local and cloud cost drivers, TXING_INVENTORY_INTERVAL_SECONDS=300, restart and NCMD redcon=4 -> 1 force-refresh options, and the AWS Budgets monthly cost alert recommendation. docs/sparkplug-lifecycle.md records REDCON 1 as the expected affordable idle-awake rig posture and REDCON 4 as deep sleep or maintenance, not normal cost control.

Final validation for closure: python -m unittest shared.aws.python.tests.test_versioning shared.aws.python.tests.test_template_policy; go test ./... in rig; git diff --check.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-23 completed. REDCON 1 is now documented and measured as the affordable idle-awake posture for raspi, local, and cloud rigs. Raspi/local idle inventory work is reduced to one 300-second SearchIndex refresh with cached registry/catalog reads and quiet unchanged logs; cloud sleeping devices tick once per minute and skip unchanged shadow/Sparkplug/witness churn; operator docs record force-refresh behavior and the AWS Budgets guardrail. All child tasks TASK-23.1 through TASK-23.4 are Done. TASK-23.1 new-device live timing remains intentionally untested per prior user decision.
<!-- SECTION:FINAL_SUMMARY:END -->
