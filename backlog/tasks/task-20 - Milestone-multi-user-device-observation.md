---
id: TASK-20
title: 'Milestone: multi-user device observation'
status: To Do
assignee: []
created_date: '2026-06-17 07:11'
labels: []
milestone: multi-user device observation
dependencies: []
references:
  - office/src/App.tsx
  - devices/unit/daemon/internal/daemon/runtime.go
  - devices/unit/board/kvs_master/src/kvs_session_real.cpp
documentation:
  - >-
    backlog/docs/architecture/multi-user-device-observation/doc-19 -
    Multi-user-device-observation-architecture.md
  - >-
    backlog/docs/milestones/multi-user-device-observation/doc-20 -
    Milestone-multi-user-device-observation.md
ordinal: 39000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Multiple signed-in users can simultaneously observe the same device state for every registered Office device type.
- [ ] #2 MCP-capable devices allow exactly one active controller while other MCP sessions remain observers until explicit takeover.
- [ ] #3 REDCON command behavior remains unchanged through the existing Sparkplug path and commandability rules.
- [ ] #4 Two browsers can view the same bot video while only one browser controls the bot.
<!-- AC:END -->
