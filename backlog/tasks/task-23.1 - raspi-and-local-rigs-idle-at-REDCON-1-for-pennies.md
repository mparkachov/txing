---
id: TASK-23.1
title: raspi and local rigs idle at REDCON 1 for pennies
status: To Do
assignee: []
created_date: '2026-07-04 16:30'
labels: []
milestone: m-2
dependencies: []
references:
  - rig/internal/registry/registry.go
  - rig/internal/rigconfig/config.go
  - rig/rig-daemon.env.template
  - docs/components/rig.md
documentation:
  - >-
    backlog/docs/architecture/rig-idle-cost-parity/doc-25 -
    Rig-REDCON-1-idle-cost-parity-architecture.md
parent_task_id: TASK-23
priority: high
ordinal: 58000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Reduce the standalone rig manager's idle-awake polling cost: inventory interval defaults to 300 seconds (code default, env template, docs), one fleet-indexing query per refresh is the steady state (device data taken from the SearchIndex documents or served from a cache instead of per-device DescribeThing), the SSM type catalog is cached across refreshes, and unchanged refreshes stop producing per-tick CloudWatch info lines. Startup and REDCON 4-to-1 resume keep refreshing immediately so a rig restart remains the manual force-refresh.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 An idle-awake raspi or local rig performs at most one fleet-indexing query and no recurring per-device registry calls or SSM reads per 300-second refresh, verified by tests and a counted soak.
- [ ] #2 A newly registered device appears in inventory within 300 seconds, and immediately after a rig restart or a REDCON 4-to-1 cycle.
- [ ] #3 Unchanged refreshes produce no recurring CloudWatch log ingestion at the default log level.
<!-- AC:END -->
