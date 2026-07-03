---
id: TASK-22.2
title: txing-mac-daemon joins the rig and converges REDCON 4-3
status: To Do
assignee: []
created_date: '2026-07-03 07:45'
labels: []
milestone: m-1
dependencies:
  - TASK-22.1
references:
  - rig/internal/protocol/protocol.go
  - rig/internal/ipc/ipc.go
  - rig/cmd/txing-thread-connectivity
  - rig/justfile
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 51000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create the txing-mac-daemon Go module with the rig IPC watch-layer role: it consumes rig inventory, publishes capability state and heartbeats for its thing, accepts REDCON commands 1-4 with pending/accepted/succeeded/failed results, and drives a redcon state machine whose power evidence lets the rig publish DBIRTH and converge REDCON 4 and 3. Includes just recipes (build/start/stop/restart/log/check/test), the daemon.env template, and wire-format tests pinned against the rig schema 2.0 payloads.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 With the rig and mac daemon running locally, the registered mac thing is born (DBIRTH) and office REDCON commands 3 and 4 converge with command feedback and correct DDATA redcon values.
- [ ] #2 Stopping the mac daemon leads to DDEATH within the capability state TTL, and restarting it re-births the device without rig restarts.
- [ ] #3 All REDCON targets 1-4 are accepted; targets above the currently achievable level converge to the highest level supported by published evidence.
- [ ] #4 The daemon is operated only through just recipes with logs and PID files under the mac run directory, and go tests cover the state machine and IPC wire formats.
<!-- AC:END -->
