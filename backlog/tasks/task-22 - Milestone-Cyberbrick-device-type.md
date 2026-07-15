---
id: TASK-22
title: 'Milestone: Cyberbrick device type'
status: To Do
assignee: []
created_date: '2026-07-15 07:36'
updated_date: '2026-07-15 07:39'
labels: []
milestone: m-3
dependencies: []
references:
  - devices/unit/manifest.toml
  - devices/unit/daemon/justfile
  - .github/workflows/release-unit.yml
  - docs/components/board.md
documentation:
  - >-
    backlog/docs/milestones/cyberbrick-device-type/doc-28 -
    Milestone-Cyberbrick-device-type.md
priority: high
ordinal: 49000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deliver the cyberbrick txing device type: a functional copy of unit (Go daemon + KVS video master + hardware worker on a Raspberry Pi Zero 2 W under a raspi rig, REDCON 4-1, board/mcp/video shadows, office visibility) whose board stack runs on Alpine Linux — aarch64 binaries dynamically linked against musl, OpenRC services, read-only root, and unit's manual mise-based install/update workflow. The watch-layer MCU stays unit's Zephyr firmware in this phase. Implementation must proceed through child tasks and must not run AWS mutation commands; AWS deploy/registration and on-device steps are prepared for the user to run manually.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Cyberbrick delivery is split into scoped child tasks for toolchain validation, catalog/UI contract, board daemons and Alpine builds, release pipeline, board runbook, and hardware parity validation.
- [ ] #2 Existing unit, mac, power, power-si, weather, and cloud-mcu device behavior is unchanged.
- [ ] #3 Completion evidence includes automated test results plus documented manual evidence covering registration, the REDCON ladder, motor/MCP parity, the documented video expectation, and read-only-root reboot survival on Alpine.
<!-- AC:END -->
