---
id: TASK-18.3
title: Move shared AWS Python MQTT helper to MQTT5
status: To Do
assignee: []
created_date: '2026-05-30 08:17'
labels: []
milestone: MQTT5 retained message expiry
dependencies: []
references:
  - shared/aws/python/src/aws/mqtt.py
  - shared/aws/python/tests/test_mqtt.py
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
ordinal: 34000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The shared AWS Python MQTT helper creates MQTT5 WebSocket connections with the existing callback and timeout behavior preserved.
- [ ] #2 Async and sync publish APIs continue to accept retain and additionally propagate optional message expiry.
- [ ] #3 Shared AWS Python tests verify retain and message expiry are passed to the MQTT5 publish path.
<!-- AC:END -->
