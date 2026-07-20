---
id: TASK-21.10
title: Thread REDCON commands are not blocked by SED maintenance polling
status: To Do
assignee: []
created_date: '2026-07-20 20:08'
labels: []
dependencies:
  - TASK-21.3
  - TASK-21.8
references:
  - rig/cmd/txing-thread-connectivity/main.go
  - rig/internal/thread/runtime.go
  - rig/internal/thread/coap.go
documentation:
  - docs/components/rig.md
  - devices/power-si/README.md
parent_task_id: TASK-21
priority: high
type: bug
ordinal: 52500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Bound end-to-end power-si REDCON command latency by preventing synchronous Thread discovery and periodic state polling from blocking command dispatch. With the device in REDCON 4 / ot mode n, the current daemon may spend one 5000 ms SED poll waiting for a maintenance GET before it reads a queued command; the command can then miss that child poll and wait for the next one, producing roughly 10 seconds of latency. Keep the existing Thread protocol, 5000 ms device poll period, 12000 ms CoAP attempt timeout, synchronous confirmed-state result contract, and REDCON 3 rn / REDCON 4 n firmware behavior.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Thread discovery and periodic state maintenance no longer execute duplicate blocking DiscoverAndPoll cycles on the command-receive event loop.
- [ ] #2 Commands are prioritized over periodic GET state work and remain serialized per device, with bounded concurrency and no unbounded goroutine or retry growth.
- [ ] #3 On a healthy Thread link, a REDCON 4 to 3 command issued while the device is in ot mode n is delivered and confirmed within one 5000 ms child poll plus bounded processing margin; REDCON 3 to 4 remains immediate while the device is receiver-on.
- [ ] #4 The change preserves the 12000 ms CoAP attempt timeout, two-attempt failure behavior, confirmed-state command result contract, existing SRP discovery, and BLE behavior.
- [ ] #5 Rig tests reproduce a command arriving behind an in-flight SED maintenance poll and verify command priority, per-device ordering, maintenance recovery, and clean daemon shutdown; manual hardware evidence records command received and transition-confirmed timestamps.
<!-- AC:END -->
