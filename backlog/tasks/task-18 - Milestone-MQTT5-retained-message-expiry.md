---
id: TASK-18
title: 'Milestone: MQTT5 retained message expiry'
status: To Do
assignee: []
created_date: '2026-05-30 08:17'
labels: []
milestone: MQTT5 retained message expiry
dependencies: []
references:
  - docs/sparkplug-lifecycle.md
  - docs/contracts/unit-device-contracts.md
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
ordinal: 31000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Repository-owned MQTT client sessions that connect directly to AWS IoT use MQTT 5 explicitly without changing public topics or payload schemas.
- [ ] #2 Dynamic retained unit board state topics expire at the configured capability TTL while descriptor topics remain retained without expiry.
- [ ] #3 Rig startup and reconnect behavior can consume retained board capability state for inventoried devices through exact subscriptions.
- [ ] #4 Validation covers unit daemon, rig, office MQTT paths, and confirms shared AWS Python has no MQTT client surface.
<!-- AC:END -->
