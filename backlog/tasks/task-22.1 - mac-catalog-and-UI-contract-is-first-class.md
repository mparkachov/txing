---
id: TASK-22.1
title: mac catalog and UI contract is first-class
status: To Do
assignee: []
created_date: '2026-07-03 07:44'
labels: []
milestone: m-1
dependencies: []
references:
  - devices/unit/manifest.toml
  - shared/aws/template.yaml
  - shared/aws/python/src/aws/type_catalog.py
  - shared/aws/scripts/aws_lib.sh
  - office/src/device-registry.ts
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 50000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Register mac as a first-class txing device type across the device manifest, shadow schemas/defaults, AWS type catalog (CloudFormation + python catalog generation + tests), certificate bundle generation, and the office UI, without changing existing device types. The office adapter renders the mac device with status detail and a video panel gated to REDCON 1, with drive control disabled.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The mac device type declares sparkplug/power/board/mcp/video capabilities, REDCON command levels 4-1, the unit-shaped redcon rules, per-capability shadow schema/default files, a web adapter, and the board video channel resource.
- [ ] #2 AWS catalog deployment material and the python type catalog include mac with identical capability data, and existing shared AWS tests plus new mac coverage pass.
- [ ] #3 Certificate bundle generation for a mac thing produces the daemon config bundle including KVS master permissions on the device video channel.
- [ ] #4 Office shows a registered mac device with the video route available at REDCON 1 and no drive controls, covered by adapter tests.
<!-- AC:END -->
