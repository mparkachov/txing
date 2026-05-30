---
id: TASK-18.4
title: Verify office MQTT5 path and retention docs
status: To Do
assignee: []
created_date: '2026-05-30 08:17'
labels: []
milestone: MQTT5 retained message expiry
dependencies: []
references:
  - office/src/shadow-api-runtime.ts
  - docs/components/board.md
  - devices/unit/docs/board-video.md
documentation:
  - >-
    backlog/docs/architecture/mqtt5-retained-message-expiry/doc-14 -
    MQTT5-retained-message-expiry-architecture.md
  - >-
    backlog/docs/milestones/mqtt5-retained-message-expiry/doc-15 -
    Milestone-MQTT5-retained-message-expiry.md
  - >-
    backlog/docs/constraints/mqtt-retained-message-policy/doc-16 -
    Constraints-MQTT-retained-message-policy.md
parent_task_id: TASK-18
ordinal: 35000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Office tests continue to verify that the browser live-shadow, Sparkplug command, and MCP MQTT paths use the existing MQTT5 client flow.
- [ ] #2 Durable board/unit documentation records which retained topics expire and which descriptor topics remain unexpired.
- [ ] #3 Rollout notes explain that old retained messages without expiry are replaced only by same-topic republishes and may need manual cleanup if orphaned.
<!-- AC:END -->
