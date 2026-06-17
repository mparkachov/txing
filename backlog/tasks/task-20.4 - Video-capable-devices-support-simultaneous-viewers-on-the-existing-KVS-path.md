---
id: TASK-20.4
title: Video-capable devices support simultaneous viewers on the existing KVS path
status: To Do
assignee: []
created_date: '2026-06-17 07:12'
labels: []
milestone: multi-user device observation
dependencies: []
references:
  - devices/unit/docs/board-video.md
  - devices/unit/board/kvs_master/src/kvs_session_real.cpp
  - devices/unit/aws/video-shadow.schema.json
documentation:
  - >-
    backlog/docs/architecture/multi-user-device-observation/doc-19 -
    Multi-user-device-observation-architecture.md
  - >-
    backlog/docs/milestones/multi-user-device-observation/doc-20 -
    Milestone-multi-user-device-observation.md
parent_task_id: TASK-20
ordinal: 43000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Video-capable devices keep the existing single AWS KVS WebRTC channel and do not add a second media path.
- [ ] #2 Two browser sessions can view the same live bot video feed during manual validation.
- [ ] #3 Any viewer-count status exposed by implementation is observability only and is not used for viewer admission control.
- [ ] #4 Documentation distinguishes multiple video viewers from multiple active MCP controllers.
<!-- AC:END -->
