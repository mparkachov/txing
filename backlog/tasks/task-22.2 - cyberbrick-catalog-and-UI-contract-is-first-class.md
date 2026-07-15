---
id: TASK-22.2
title: cyberbrick catalog and UI contract is first-class
status: To Do
assignee: []
created_date: '2026-07-15 07:36'
labels: []
milestone: m-3
dependencies: []
references:
  - devices/unit/manifest.toml
  - shared/aws/template.yaml
  - shared/aws/python/src/aws/type_catalog.py
  - shared/aws/scripts/aws_lib.sh
  - office/src/device-registry.ts
documentation:
  - >-
    backlog/docs/architecture/cyberbrick-device-type/doc-27 -
    Cyberbrick-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 51000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Register cyberbrick as a first-class txing device type across the device manifest, shadow schemas/defaults, AWS type catalog (CloudFormation + python catalog generation + tests), certificate bundle generation, and the office UI, without changing existing device types. Unit parity: full capability set including ble, REDCON 4-1 with unit's rules, board video channel resource, unit-equivalent office panel behavior.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The cyberbrick device type declares sparkplug/ble/power/board/mcp/video capabilities, REDCON command levels 4-1 with unit-shaped rules, per-capability shadow schema/default files, a web adapter, and the board video channel resource.
- [ ] #2 AWS catalog deployment material and the python type catalog include cyberbrick with identical capability data, and shared AWS tests plus new cyberbrick coverage pass.
- [ ] #3 Certificate bundle generation for a cyberbrick thing produces a cyberbrick-daemon config bundle including KVS master permissions on the device video channel.
- [ ] #4 Office shows a registered cyberbrick device with unit-equivalent panel behavior (teleop, video at REDCON 1), covered by adapter and registry tests.
<!-- AC:END -->
