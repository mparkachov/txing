---
id: TASK-20.2
title: Office exposes single active MCP controller state
status: To Do
assignee: []
created_date: '2026-06-17 07:11'
labels: []
milestone: multi-user device observation
dependencies: []
references:
  - office/src/shadow-api-runtime.ts
  - office/src/shadow-api.ts
  - devices/unit/web/TxingPanel.tsx
documentation:
  - >-
    backlog/docs/architecture/multi-user-device-observation/doc-19 -
    Multi-user-device-observation-architecture.md
  - >-
    backlog/docs/milestones/multi-user-device-observation/doc-20 -
    Milestone-multi-user-device-observation.md
parent_task_id: TASK-20
ordinal: 41000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Office distinguishes no active MCP owner, current-browser owner, and another-session owner for MCP-capable devices.
- [ ] #2 Observer sessions cannot drive before ownership is known or while another MCP session owns active control.
- [ ] #3 Explicit takeover sends control.activate with takeover true and then enables control only after the current browser owns the active MCP session.
- [ ] #4 MCP actor metadata identifies the signed-in user rather than a static browser label.
<!-- AC:END -->
