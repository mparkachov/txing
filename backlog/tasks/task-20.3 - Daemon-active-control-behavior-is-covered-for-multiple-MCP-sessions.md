---
id: TASK-20.3
title: Daemon active-control behavior is covered for multiple MCP sessions
status: To Do
assignee: []
created_date: '2026-06-17 07:12'
labels: []
milestone: multi-user device observation
dependencies: []
references:
  - devices/unit/daemon/internal/daemon/runtime.go
  - devices/unit/daemon/internal/daemon/runtime_test.go
  - devices/unit/aws/mcp-shadow.schema.json
documentation:
  - >-
    backlog/docs/architecture/multi-user-device-observation/doc-19 -
    Multi-user-device-observation-architecture.md
  - >-
    backlog/docs/milestones/multi-user-device-observation/doc-20 -
    Milestone-multi-user-device-observation.md
parent_task_id: TASK-20
ordinal: 42000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Multiple MCP sessions can perform read-only state calls without becoming active controller.
- [ ] #2 A non-owner MCP session cannot execute actuator tools without explicit takeover.
- [ ] #3 Explicit takeover switches active owner and epoch, stops previous motion, and prevents the old epoch from continuing control.
- [ ] #4 The MCP shadow/schema/docs describe the active-control status consumed by Office.
<!-- AC:END -->
