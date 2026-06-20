---
id: TASK-21.3
title: rig Thread connectivity drives power-si over CoAP
status: Done
assignee:
  - '@Codex'
created_date: '2026-06-20 07:12'
updated_date: '2026-06-20 12:49'
labels: []
milestone: m-0
dependencies:
  - TASK-21.1
  - TASK-21.2
references:
  - rig/internal/protocol
  - rig/internal/manager
  - rig/cmd
documentation:
  - >-
    backlog/docs/architecture/power-si-thread-device/doc-21 -
    power-si-Thread-device-type-architecture.md
parent_task_id: TASK-21
priority: high
ordinal: 47000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add rig Thread connectivity for power-si devices through a dedicated daemon that discovers SRP services, speaks CoAP to devices, and publishes state through the existing local IPC/Sparkplug path.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 txing-thread-connectivity runs as a separate rig daemon, assumes external OTBR readiness, discovers _txing-coap._udp services under default.service.arpa, and filters records to power-si devices.
- [x] #2 The daemon maps SRP service instances to Thing names, reads CoAP state, sends REDCON 3/4 commands, reports command success only after confirmed device state, and publishes thread/power shadow updates through v2 IPC.
- [x] #3 Sparkplug manager transport logic supports Thread REDCON evidence for power-si while existing BLE devices and metrics remain behaviorally unchanged.
- [x] #4 Rig Go tests cover SRP record parsing/filtering, CoAP success and failure paths, unavailable devices, command result publication, and manager capability gating.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect existing BLE connectivity, v2 IPC, Sparkplug manager capability gating, rig config, service docs, and tests.
2. Add a focused Thread connectivity package/daemon that performs DNS-SD/SRP record filtering, CoAP state polling/REDCON command confirmation, and publishes thread/power updates through existing IPC.
3. Generalize manager transport evidence so power-si can use Thread REDCON state without changing current BLE behavior.
4. Add Go tests for SRP parsing/filtering, CoAP success/failure/unavailable handling, command publication, and manager gating.
5. Run rig tests and record validation evidence without configuring OTBR or touching external services.
<!-- SECTION:PLAN:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-06-20 12:49
---
Implementation complete.

Delivered:
- Added txing-thread-connectivity as a standalone rig daemon under rig/cmd/txing-thread-connectivity. It consumes existing v2 IPC inventory/command topics, assumes external OTBR readiness, discovers _txing-coap._udp services under default.service.arpa, filters TXT type=power-si, maps DNS-SD service instances to Thing names, polls CoAP state, sends REDCON 3/4 commands, and publishes capability state, command results, thread shadow updates, and power battery shadow updates through the existing IPC path.
- Added rig/internal/thread with DNS-SD/SRP PTR/SRV/TXT/AAAA discovery, a minimal Confirmable CoAP JSON client for GET /txing/v1/state and PUT /txing/v1/redcon, Thread capability-state helpers, and runtime command/poll coordination.
- Generalized manager REDCON 4 transport evidence by adding protocol.TransportRedconMetric while preserving existing protocol.BleRedconMetric behavior.
- Fixed cross-adapter command routing so BLE ignores Thread-only devices and Thread ignores BLE-only devices instead of publishing unrelated rejected command results.
- Added rig build/start/stop/log/check wiring, rig release packaging, root-owned mise config, rig daemon env defaults, and service/docs updates for txing-thread-connectivity.

Validation passed:
- cd rig && go test ./...
- python3 -m unittest shared/aws/python/tests/test_versioning.py
- just --justfile rig/justfile build
- git diff --check

No OTBR setup, hardware access, AWS mutation, or flashing/programming commands were run.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-21.3 is implemented. The rig now has a separate txing-thread-connectivity daemon for power-si Thread/CoAP devices, manager transport evidence supports Thread REDCON state while preserving BLE behavior, release/service/docs include the third rig daemon, and targeted Go plus docs/versioning validation passes.
<!-- SECTION:FINAL_SUMMARY:END -->
