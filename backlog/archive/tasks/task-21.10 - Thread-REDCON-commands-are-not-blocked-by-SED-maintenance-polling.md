---
id: TASK-21.10
title: Thread REDCON commands are not blocked by SED maintenance polling
status: Done
assignee:
  - '@root'
created_date: '2026-07-20 20:08'
updated_date: '2026-07-27 20:12'
labels: []
dependencies: []
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
  - devices/power-si/mcu/src/main.c
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
- [x] #3 On a healthy Thread link, a REDCON 4 to 3 command issued while the device is in ot mode n is delivered and confirmed within one 5000 ms child poll plus bounded processing margin; REDCON 3 to 4 remains immediate while the device is receiver-on.
- [x] #4 The change preserves the 12000 ms CoAP attempt timeout, two-attempt failure behavior, confirmed-state command result contract, existing SRP discovery, and BLE behavior.
- [x] #5 Rig tests reproduce a command arriving behind an in-flight SED maintenance poll and verify command priority, per-device ordering, maintenance recovery, and clean daemon shutdown; manual hardware evidence records command received and transition-confirmed timestamps.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Isolate discovery and periodic GET maintenance from the IPC receive path and coalesce overlapping maintenance triggers so only one discovery/poll cycle is active. 2. Add a bounded Thread work scheduler that gives queued REDCON commands priority, cancels an in-flight per-device maintenance GET when a command arrives, and serializes all CoAP work for each device without growing goroutines or retries. 3. Keep the existing CoAP client (12 s attempt timeout, two attempts), endpoint/SRP discovery, result confirmation, and BLE contracts unchanged. 4. Add deterministic rig tests covering a command behind a blocked SED GET, same-device ordering, maintenance resumption, and cancellation/daemon shutdown; run the focused Go tests and the rig test suite. 5. Record the required manual SED hardware timestamp evidence as a rollout check rather than fabricating it.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented a bounded four-worker Thread scheduler: one command slot remains reserved while up to three maintenance GETs run; commands are selected first and cancel an active GET for the same device. Discovery plus maintenance is coalesced into one cycle, runs outside the IPC receive loop, and shutdown cancels and joins all scheduler workers. Runtime publication remains serialized and unavailable/failed polls retain one offline publication. Added deterministic scheduler tests for blocked-SED priority, overlapping-cycle coalescing, per-device command ordering, maintenance recovery, and shutdown, plus offline publication regressions. Validation: go test -race ./internal/thread -count=1; just rig::test; go vet ./.... Manual SED validation remains required: retain the new command-received and transition-confirmed journal timestamps for REDCON 4->3 (one 5000 ms poll plus margin) and 3->4 (immediate receiver-on behavior).

Hardware evidence 2026-07-27: daemon ingress was immediate, but SED confirmation is not yet acceptable. REDCON 4->3 confirmations took 6562 ms (18:43:20.383 to 18:43:26.944) and 6163 ms (18:45:32.053 to 18:45:38.216). REDCON 3->4 confirmations were absent for commands at 18:43:33 and 18:45:12, 3984 ms at 18:45:12 to 18:45:16.188, and 17972 ms at 18:45:49.522 to 18:46:07.493. The 17972 ms sample matches a 12000 ms first CoAP attempt timing out followed by a retry and one SED poll. Firmware inspection shows sed-debug applies rxOnWhenIdle=false before it sends the CoAP Changed response; the LED/output changes immediately but the response can be delayed or lost once the device becomes sleepy. Command receipt is scheduler ingress only; missing confirmed lines currently lack a daemon-side failure log because command failures publish IPC results rather than returning an error. Acceptance criteria 3 and 5 remain open pending an approved firmware response-order fix and rerun.

Correction to the preceding hardware note: the REDCON 3->4 command at 18:45:12.305 did confirm at 18:45:16.188 (3984 ms). The command with no confirmation is only the 18:43:33.797 REDCON 3->4 request. The 18:45:49.522 REDCON 3->4 request confirmed after 17972 ms.

Approved response-order correction: sed-debug/sed-current REDCON 4 now publishes the CoAP changed-state response while receiver-on, schedules the existing Thread n link-mode transition after a bounded 100 ms grace, and uses an atomic pending flag so a newer REDCON 3 cancels the deferred sleep. REDCON 3 behavior, 5000 ms poll period, and rig CoAP timeout/retry contract are unchanged. Validation: just power-si::mcu::build-sed-debug and just power-si::mcu::build-sed-current both produced zephyr.hex and zephyr.elf. Manual flash and timestamp validation remains required; no flashing was performed.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-07-20 20:18
---
Hardware observation (2026-07-20): with the board in REDCON 4 / ot mode n and a 5000 ms poll period, the first Office REDCON 3 request sometimes completes after roughly 10 seconds rather than one poll period. REDCON 3 to 4 completes almost immediately while the device is receiver-on (ot mode rn). This confirms the command can arrive behind an in-flight periodic state GET, miss the current poll, and wait for the following poll. Firmware transition behavior itself is correct; the outstanding work is rig scheduling and command priority.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed Thread REDCON scheduling and response-order reliability fix. The rig now coalesces maintenance off the IPC receive loop, prioritizes bounded per-device commands, and cancels an in-flight same-device maintenance GET. The sed-debug/sed-current firmware now sends the REDCON 4 CoAP changed-state response while receiver-on and changes to sleepy n after a 100 ms grace. Automated validation passed: go test -race ./internal/thread -count=1, just rig::test, go vet ./..., just power-si::mcu::build-sed-debug, and just power-si::mcu::build-sed-current. Hardware evidence 2026-07-27 after rig-daemon restart: REDCON 4->3 confirmed in 1679.742 ms and 3740.244 ms (within one 5000 ms child poll); REDCON 3->4 confirmed in 129.140 ms and 137.508 ms while receiver-on. The logs also show clean daemon shutdown and restart.
<!-- SECTION:FINAL_SUMMARY:END -->
