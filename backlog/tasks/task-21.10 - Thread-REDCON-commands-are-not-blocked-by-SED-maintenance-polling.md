---
id: TASK-21.10
title: Thread REDCON commands are not blocked by SED maintenance polling
status: In Progress
assignee:
  - '@root'
created_date: '2026-07-20 20:08'
updated_date: '2026-07-27 14:36'
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
modified_files:
  - rig/cmd/txing-thread-connectivity/main.go
  - rig/internal/thread/runtime.go
  - rig/internal/thread/scheduler.go
  - rig/internal/thread/scheduler_test.go
  - rig/internal/thread/protocol_test.go
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
- [x] #1 Thread discovery and periodic state maintenance no longer execute duplicate blocking DiscoverAndPoll cycles on the command-receive event loop.
- [x] #2 Commands are prioritized over periodic GET state work and remain serialized per device, with bounded concurrency and no unbounded goroutine or retry growth.
- [ ] #3 On a healthy Thread link, a REDCON 4 to 3 command issued while the device is in ot mode n is delivered and confirmed within one 5000 ms child poll plus bounded processing margin; REDCON 3 to 4 remains immediate while the device is receiver-on.
- [x] #4 The change preserves the 12000 ms CoAP attempt timeout, two-attempt failure behavior, confirmed-state command result contract, existing SRP discovery, and BLE behavior.
- [ ] #5 Rig tests reproduce a command arriving behind an in-flight SED maintenance poll and verify command priority, per-device ordering, maintenance recovery, and clean daemon shutdown; manual hardware evidence records command received and transition-confirmed timestamps.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Isolate discovery and periodic GET maintenance from the IPC receive path and coalesce overlapping maintenance triggers so only one discovery/poll cycle is active. 2. Add a bounded Thread work scheduler that gives queued REDCON commands priority, cancels an in-flight per-device maintenance GET when a command arrives, and serializes all CoAP work for each device without growing goroutines or retries. 3. Keep the existing CoAP client (12 s attempt timeout, two attempts), endpoint/SRP discovery, result confirmation, and BLE contracts unchanged. 4. Add deterministic rig tests covering a command behind a blocked SED GET, same-device ordering, maintenance resumption, and cancellation/daemon shutdown; run the focused Go tests and the rig test suite. 5. Record the required manual SED hardware timestamp evidence as a rollout check rather than fabricating it.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented a bounded four-worker Thread scheduler: one command slot remains reserved while up to three maintenance GETs run; commands are selected first and cancel an active GET for the same device. Discovery plus maintenance is coalesced into one cycle, runs outside the IPC receive loop, and shutdown cancels and joins all scheduler workers. Runtime publication remains serialized and unavailable/failed polls retain one offline publication. Added deterministic scheduler tests for blocked-SED priority, overlapping-cycle coalescing, per-device command ordering, maintenance recovery, and shutdown, plus offline publication regressions. Validation: go test -race ./internal/thread -count=1; just rig::test; go vet ./.... Manual SED validation remains required: retain the new command-received and transition-confirmed journal timestamps for REDCON 4->3 (one 5000 ms poll plus margin) and 3->4 (immediate receiver-on behavior).
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-07-20 20:18
---
Hardware observation (2026-07-20): with the board in REDCON 4 / ot mode n and a 5000 ms poll period, the first Office REDCON 3 request sometimes completes after roughly 10 seconds rather than one poll period. REDCON 3 to 4 completes almost immediately while the device is receiver-on (ot mode rn). This confirms the command can arrive behind an in-flight periodic state GET, miss the current poll, and wait for the following poll. Firmware transition behavior itself is correct; the outstanding work is rig scheduling and command priority.
---
<!-- COMMENTS:END -->
