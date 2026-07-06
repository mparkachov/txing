---
id: TASK-20
title: 'Milestone: multi-user device observation'
status: Done
assignee: []
created_date: '2026-06-17 07:11'
updated_date: '2026-07-06 11:12'
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
- [x] #1 Multiple signed-in users can simultaneously observe the same device state for every registered Office device type.
- [x] #2 MCP-capable devices allow exactly one active controller while other MCP sessions remain observers until explicit takeover.
- [x] #3 REDCON command behavior remains unchanged through the existing Sparkplug path and commandability rules.
- [x] #4 Two browsers can view the same bot video while only one browser controls the bot.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Epic completion audit on 2026-07-06:
- TASK-20.1 is Done and covers multi-user same-device observation, non-MCP view-only device types, and unchanged Sparkplug REDCON commandability.
- TASK-20.2 is Done and covers Office MCP ownership states, observer drive blocking, explicit takeover, and signed-in user actor metadata.
- TASK-20.3 is Done and covers daemon multi-session MCP policy, non-owner actuator rejection, explicit takeover, epoch protection, and activeControl status/schema/docs.
- TASK-20.4 is Done and covers the existing single AWS KVS video path, observability-only viewer state, documentation separation of video viewers from MCP active control, and manual Firefox/Chrome two-user REDCON 1 video validation on 2026-07-06.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-20 completed. All four subtasks are Done, all epic acceptance criteria are checked, REDCON remains on the existing Sparkplug command path, Office supports simultaneous observers with exactly one active MCP controller and explicit takeover, daemon multi-session active-control behavior is covered, and manual validation confirmed two different browsers with two different users viewing live REDCON 1 bot video.
<!-- SECTION:FINAL_SUMMARY:END -->
