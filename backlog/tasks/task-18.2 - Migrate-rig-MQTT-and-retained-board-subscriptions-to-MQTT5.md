---
id: TASK-18.2
title: Migrate rig MQTT and retained board subscriptions to MQTT5
status: To Do
assignee: []
created_date: '2026-05-30 08:17'
labels: []
milestone: MQTT5 retained message expiry
dependencies: []
references:
  - rig/internal/mqttx/mqttx.go
  - rig/cmd/txing-sparkplug-manager/main.go
  - rig/cmd/txing-sparkplug-manager/main_test.go
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
ordinal: 33000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Rig MQTT sessions use an MQTT5-capable Go client and preserve current TLS, clean session, will, reconnect, QoS 1 publish, and subscribe behavior.
- [ ] #2 Sparkplug publications remain non-retained and preserve the current topic and payload contracts.
- [ ] #3 SparkplugManager subscribes to exact retained board capability-state topics for every inventoried device in addition to its live wildcard subscription.
- [ ] #4 Rig tests cover exact retained subscriptions and non-retained Sparkplug publications.
<!-- AC:END -->
