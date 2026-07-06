---
id: TASK-23.2
title: cloud rig ticks are change-aware and redcon-paced
status: In Progress
assignee:
  - '@codex'
created_date: '2026-07-04 16:30'
updated_date: '2026-07-06 08:11'
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
- [x] #2 Waking, sleeping, and DCMD command convergence behave exactly as before, including command feedback metrics and ECS task reconciliation at REDCON 3.
- [x] #3 Witness projections and office views remain unchanged for both sleeping and awake devices.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Keep the cloud rig NBIRTH minute refresh unchanged to avoid silently changing the Sparkplug liveness contract.
2. Add cloud-mcu tick state comparison helpers so sqs and power named shadows are updated only when their reported payload changes.
3. Make device Sparkplug publication change-aware: publish DBIRTH when not born, publish DDATA for redcon/capability/command-result changes, and allow at most one unchanged liveness DDATA per device per minute.
4. Make scheduler tick cadence redcon-aware by reading cached device power state: sleeping/default devices receive one immediate tick per minute; REDCON 3 devices keep the 0,6,...,54 second fanout.
5. Avoid per-tick device identity DescribeThing by carrying/caching identity from scheduler-originated tick payloads while preserving DCMD validation.
6. Add tests for unchanged sleeping ticks, changed ticks/command feedback, scheduler cadence selection, REDCON 3 ECS behavior, and unchanged witness-facing Sparkplug projections.
7. Run cloud-mcu Go tests and update TASK-23.2 evidence with residual live counted-soak notes.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented 2026-07-06 local code/test pass for change-aware cloud rig ticks.

- Cloud rig scheduler still publishes minute NBIRTH, then chooses SQS tick cadence from the device power shadow: default/sleeping devices get one offset-0 tick per minute; desired REDCON 3 devices keep offsets 0,6,...,54 for ECS reconciliation.
- Cloud MCU ticks no longer perform per-tick DescribeThing and no longer write the sqs shadow. The power shadow is written only when rendered reported state changes, and device Sparkplug DBIRTH/DDATA is published only for first birth, REDCON/capability changes, or command feedback. Unchanged sleeping and unchanged REDCON 3 ticks publish nothing and write no shadows.
- DCMD remains registry-validated, writes desired REDCON plus pending command to the power shadow, and now queues one immediate offset-0 SQS tick so command convergence does not wait for the next minute schedule.
- CloudFormation updates: cloud rig runtime can GetThingShadow for cadence selection; cloud MCU runtime has CLOUD_MCU_TICK_QUEUE_URL and sqs:SendMessage for DCMD-triggered immediate ticks.
- Automated evidence: go test -tags lambda.norpc ./... in devices/cloud-mcu/lambda; go test ./... in witness; bun test in office; python -m unittest shared.aws.python.tests.test_template_policy; git diff --check.
- AC #1 live counted soak remains pending: after deploying the CloudFormation/template and Lambda artifact changes, run a sleeping cloud-mcu device idle for several schedule windows and confirm one scheduled SQS tick per minute with no recurring cloud-mcu UpdateThingShadow calls and no recurring device DBIRTH/DDATA/witness invocations after the stable state is born.

Documented the TASK-23.2 idle counted-soak procedure in devices/cloud-mcu/README.md. The runbook keeps default Lambda logging unchanged and tells the operator to verify, after deploy, one cloud MCU SQS invocation per sleeping device per minute, no recurring cloud MCU UpdateThingShadow calls for the stable sleeping device, and no recurring device DBIRTH/DDATA or witness projection movement; cloud rig node NBIRTH minute liveness is explicitly excluded from the device publish count.

Added unit evidence for the AC #1 steady-state shape: TestSleepingDeviceIdleWindowsSendOneTickAndNoRecurringWritesOrPublishes simulates five one-minute sleeping-device schedule windows through the scheduler and runtime together. It asserts one offset-0 tick per minute, exactly one initial device DBIRTH/power-shadow born-state write, no sqs shadow writes, and no recurring device Sparkplug publishes or power shadow writes during the stable sleeping windows. This strengthens the required unit-test portion of AC #1; the live counted soak remains pending.
<!-- SECTION:NOTES:END -->
