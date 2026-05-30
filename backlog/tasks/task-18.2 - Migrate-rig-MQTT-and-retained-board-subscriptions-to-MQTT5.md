---
id: TASK-18.2
title: Migrate rig MQTT and retained board subscriptions to MQTT5
status: Done
assignee:
  - '@codex'
created_date: '2026-05-30 08:17'
updated_date: '2026-05-30 08:51'
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
- [x] #1 Rig MQTT sessions use an MQTT5-capable Go client and preserve current TLS, clean session, will, reconnect, QoS 1 publish, and subscribe behavior.
- [x] #2 Sparkplug publications remain non-retained and preserve the current topic and payload contracts.
- [x] #3 SparkplugManager subscribes to exact retained board capability-state topics for every inventoried device in addition to its live wildcard subscription.
- [x] #4 Rig tests cover exact retained subscriptions and non-retained Sparkplug publications.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect rig MQTT wrapper, SparkplugManager inventory/subscription flow, and current tests.
2. Replace the MQTT3 Paho wrapper with an MQTT5-capable client while preserving TLS, clean session, will, reconnect, QoS 1 publish, and subscribe semantics at the local mqttx interface.
3. Add exact retained board capability-state subscriptions for inventoried devices while keeping the wildcard live subscription.
4. Add/update rig tests for exact retained subscriptions and non-retained Sparkplug publications.
5. Run just rig::test, record validation in Backlog, and close the task only after acceptance criteria are proven.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented rig MQTT5 migration with github.com/eclipse/paho.golang/autopaho, preserving TLS, clean start/session expiry 0, automatic reconnect, will, QoS 1 subscribe, and QoS 1 publish semantics. Added exact retained board capability-state subscriptions for inventoried devices on inventory refresh and node MQTT reconnect while keeping the live wildcard subscription. Added tests for MQTT5 client defaults, exact retained subscription restoration/deduplication, and non-retained Sparkplug node/device publications. Validation: just rig::test passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Rig MQTT now uses the MQTT5 AutoPaho client, retained board capability-state replay includes exact per-device subscriptions on inventory refresh and reconnect, and Sparkplug publications remain non-retained. Validation: just rig::test passed.
<!-- SECTION:FINAL_SUMMARY:END -->
