---
id: TASK-21.3
title: rig Thread connectivity drives power-si over CoAP
status: To Do
assignee: []
created_date: '2026-06-20 07:12'
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
- [ ] #1 txing-thread-connectivity runs as a separate rig daemon, assumes external OTBR readiness, discovers _txing-coap._udp services under default.service.arpa, and filters records to power-si devices.
- [ ] #2 The daemon maps SRP service instances to Thing names, reads CoAP state, sends REDCON 3/4 commands, reports command success only after confirmed device state, and publishes thread/power shadow updates through v2 IPC.
- [ ] #3 Sparkplug manager transport logic supports Thread REDCON evidence for power-si while existing BLE devices and metrics remain behaviorally unchanged.
- [ ] #4 Rig Go tests cover SRP record parsing/filtering, CoAP success and failure paths, unavailable devices, command result publication, and manager capability gating.
<!-- AC:END -->
