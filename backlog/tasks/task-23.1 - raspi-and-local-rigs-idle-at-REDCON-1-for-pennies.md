---
id: TASK-23.1
title: raspi and local rigs idle at REDCON 1 for pennies
status: In Progress
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
- [x] #3 Unchanged refreshes produce no recurring CloudWatch log ingestion at the default log level.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented 2026-07-06; unit-test coverage is in place, the live counted soak
and new-device timing check remain to be run on a rig.

- `rig/internal/rigconfig/config.go` + `rig/rig-daemon.env.template`:
  `TXING_INVENTORY_INTERVAL_SECONDS` default 30 -> 300 (test:
  `TestLoadDefaultsInventoryIntervalToFiveMinutes`).
- `rig/internal/registry/registry.go`: `LoadInventory` now builds device
  registrations from the fleet-indexing `SearchIndex` documents (no per-device
  `DescribeThing`), caches the rig's own thing type after the first call, and
  caches the SSM type catalog for `TypeCatalogCacheTTL` (1h). Cumulative
  `Counts()` (SearchIndex/DescribeThing/SSMReads) support counted soaks.
  Tests: `TestLoadInventoryUsesOneSearchQueryAndCachesRegistryReads`,
  `TestLoadInventoryReloadsTypeCatalogAfterTTL`,
  `TestLoadInventoryFiltersUnmanagedSearchDocuments` assert 1 search query and
  0 recurring registry/SSM calls per steady-state refresh.
- `rig/cmd/txing-sparkplug-manager/main.go`: unchanged refreshes publish no
  IPC inventory and log nothing at info (debug-only line includes the AWS call
  counters); the retained IPC publish and info log happen only when the
  inventory changed, so the Thread daemon's reconcile info line also goes
  quiet at idle. Tests: `TestRefreshInventoryPublishesOnlyOnChange`,
  `TestNodeRedconOneCommandRefreshesInventoryImmediately`.
- `docs/components/rig.md`: new default, idle-cost contract, and health-check
  expectations documented.

Counted soak runbook (AC #1): run the rig idle-awake at REDCON 1 with
`TXING_RIG_DEBUG=true` for >= 3 refresh windows and read the
`inventory refresh unchanged ... awsCalls searchIndex=N describeThing=M
ssmReads=K` debug lines: N grows by 1 per 300 s tick, M stays at 1 (startup
rig describe), K stays at the initial catalog load count until the 1 h TTL.
AC #2 live check: register a device, confirm it appears within 300 s, then
confirm immediate appearance after a rig restart and after an NCMD 4 -> 1
cycle.
<!-- SECTION:NOTES:END -->
