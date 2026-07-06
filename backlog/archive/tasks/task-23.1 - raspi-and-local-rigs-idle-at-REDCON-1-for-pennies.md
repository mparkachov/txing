---
id: TASK-23.1
title: raspi and local rigs idle at REDCON 1 for pennies
status: Done
assignee: []
created_date: '2026-07-04 16:30'
updated_date: '2026-07-06 07:51'
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
- [x] #1 An idle-awake raspi or local rig performs at most one fleet-indexing query and no recurring per-device registry calls or SSM reads per 300-second refresh, verified by tests and a counted soak.
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

Live startup evidence from attached 2026-07-06 raspi journal: updated rig services start as version 0.15.5 with debug output enabled. txing-sparkplug-manager logs version for rig=raspi-6q6abe/town-jhgjjd, connects Sparkplug MQTT at 07:32:09Z, and publishes the initial inventory at 07:32:10Z with rigType=raspi devices=4. txing-ble-connectivity then reconciles devices=3 and publishes BLE capability-state debug samples. No sparkplug-manager warning/error appears in the captured window. This is useful startup/immediate-refresh evidence, but it is not the counted idle soak for AC #1: the capture ends before the first 300-second unchanged refresh and contains no 'inventory refresh unchanged ... awsCalls searchIndex=N describeThing=M ssmReads=K' line.

AC #2 live validation is explicitly not required for this TASK-23.1 verification pass per user direction on 2026-07-06. Do not block the current AC #1 counted-soak confirmation on registering a new device or running a live REDCON 4 -> 1 cycle; those can be revisited separately if needed.

AC #1 counted-soak evidence from 2026-07-06 raspi debug journal: unchanged refresh counters were searchIndex=2/3/4/5, describeThing=1 throughout, ssmReads=13 throughout, devices=4 throughout. User moved REDCON 1 -> 4 -> 1 around minute 41; the 07:41:55Z unchanged refresh added exactly one SearchIndex call with no additional DescribeThing or SSM reads, then the scheduled 07:42:10Z and 07:47:10Z refreshes also each added exactly one SearchIndex call. This confirms no recurring per-device registry calls or SSM reads during the counted soak window.

Closure decision: AC #2 live validation will not be tested for TASK-23.1 per user direction on 2026-07-06. The task is closed with AC #2 intentionally unverified; startup and REDCON 4 -> 1 immediate-refresh behavior remain covered by unit tests and the live counted soak included a REDCON 1 -> 4 -> 1 transition, but no newly registered device timing test was run.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-23.1 reduced raspi/local rig idle inventory cost: default inventory interval is 300 seconds, inventory records are built from fleet-indexing SearchIndex documents without per-device DescribeThing, rig thing type and SSM catalog reads are cached, and unchanged refreshes do not publish IPC inventory or log at info level. Validation: focused Go tests, full rig test suite, race tests for registry/manager paths, and a live raspi counted soak. Soak evidence showed searchIndex=2/3/4/5 while describeThing stayed 1 and ssmReads stayed 13, including across a live REDCON 1 -> 4 -> 1 transition. AC #2 new-device timing was intentionally not live-tested by user decision for this closure.
<!-- SECTION:FINAL_SUMMARY:END -->
