---
id: TASK-22
title: 'Milestone: Mac end-device client'
status: To Do
assignee: []
created_date: '2026-07-03 07:44'
labels: []
milestone: m-1
dependencies: []
references:
  - devices/unit/manifest.toml
  - rig/internal/protocol/protocol.go
  - devices/unit/daemon
  - devices/unit/board/kvs_master
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
  - >-
    backlog/docs/milestones/mac-device-type/doc-24 -
    Milestone-Mac-device-type.md
priority: high
ordinal: 49000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deliver the mac txing device type: the development Mac registers in AWS IoT, is born as a Sparkplug device under the locally running rig, converges through REDCON 4-1, and streams the Mac camera over AWS KVS WebRTC at REDCON 1 for the office viewer. Dev-only scope (no systemd/release packaging). Implementation must proceed through child tasks and must not run AWS mutation commands; AWS deploy/registration steps are prepared for the user to run manually.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Mac device implementation is split into scoped child tasks for catalog/UI, daemon watch layer, daemon action layer, macOS video worker, and REDCON 1 e2e validation.
- [ ] #2 Existing unit, power, power-si, weather, and cloud-mcu device behavior is unchanged.
- [ ] #3 Completion evidence includes automated test results plus a documented manual runbook covering registration, the REDCON ladder, and office-visible camera video.
<!-- AC:END -->
