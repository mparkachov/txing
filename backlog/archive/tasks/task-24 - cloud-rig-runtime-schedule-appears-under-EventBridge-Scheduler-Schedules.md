---
id: TASK-24
title: cloud rig runtime schedule appears under EventBridge Scheduler Schedules
status: Done
assignee: []
created_date: '2026-07-05 04:28'
updated_date: '2026-07-05 04:33'
labels: []
dependencies: []
references:
  - devices/cloud-mcu/lambda/cmd/txing-cloud-rig-lambda/template.yaml
  - devices/cloud-mcu/lambda/internal/cloudmcu/cloudmcu.go
ordinal: 61000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
AWS console now lists the town-cloud-rig-runtime EventBridge schedule rule under Schedule rules (legacy). The cloud rig runtime tick schedule should be defined as an EventBridge Scheduler schedule so it appears in the new Schedules section, with no functional change to tick cadence or the REDCON-driven enable/disable behavior.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The cloud rig runtime tick schedule is an EventBridge Scheduler schedule named after the environment stack (for example town-cloud-rig-runtime) and no legacy EventBridge schedule rule remains in the cloud rig stack.
- [x] #2 The cloud rig lambda still enables and disables its own tick schedule with least-privilege IAM, and tick cadence, targets, and payload behavior are unchanged.
- [x] #3 Template policy and lambda unit tests pass and reflect the Scheduler-based configuration.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Replaced the AWS::Events::Rule + lambda permission in the cloud rig stack with an AWS::Scheduler::Schedule (default group, FlexibleTimeWindow OFF) invoked via a new scheduler execution role. Lambda toggle now uses scheduler GetSchedule/UpdateSchedule (state-only rewrite, no-op when state already matches) with least-privilege scheduler + iam:PassRole permissions. Env var renamed to CLOUD_RIG_SCHEDULE_NAME, SSM parameter to /txing/stack/CloudRigRuntimeScheduleName (no external consumers). eventbridge SDK dependency replaced by scheduler SDK. Template policy tests and lambda unit tests updated and passing. Requires stack redeploy plus lambda artifact republish; schedule deploys ENABLED like the old rule.
<!-- SECTION:NOTES:END -->
