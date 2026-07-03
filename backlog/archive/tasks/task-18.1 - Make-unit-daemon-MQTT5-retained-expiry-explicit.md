---
id: TASK-18.1
title: Make unit daemon MQTT5 retained expiry explicit
status: Done
assignee:
  - '@codex'
created_date: '2026-05-30 08:17'
updated_date: '2026-05-30 08:25'
labels: []
milestone: MQTT5 retained message expiry
dependencies: []
references:
  - devices/unit/daemon/internal/daemon/runtime.go
  - devices/unit/daemon/internal/daemon/topics.go
  - devices/unit/daemon/internal/daemon/runtime_test.go
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
modified_files:
  - devices/unit/daemon/internal/daemon/runtime.go
  - devices/unit/daemon/internal/daemon/runtime_test.go
parent_task_id: TASK-18
ordinal: 32000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The unit daemon connects, subscribes, publishes, acknowledges, and parses inbound publishes using MQTT 5 packets while preserving current QoS 1 behavior.
- [x] #2 Retained capability state, MCP status, and video status publishes carry message expiry equal to the configured capability TTL.
- [x] #3 Retained MCP and video descriptors remain retained without message expiry.
- [x] #4 Unit daemon tests verify MQTT5 packet encoding/parsing and retained expiry policy.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the unit daemon MQTT packet code and existing runtime tests around retained publishes.\n2. Extend PublishedMessage with optional message expiry and route dynamic retained state topics through a capability-TTL expiry policy while keeping descriptors unexpired.\n3. Update the custom MQTT packet encoder/parser to MQTT 5: CONNECT protocol level, property length handling for CONNACK/PUBLISH/SUBSCRIBE/PUBACK, and PUBLISH message-expiry properties.\n4. Add focused unit tests for MQTT5 packet shapes, retained expiry assignment, and descriptor no-expiry behavior.\n5. Run the unit daemon test suite and update the task with validation notes.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented MQTT5 packet handling in the unit daemon custom MQTT encoder/parser. CONNECT now sends MQTT protocol level 5 with clean start and explicit session expiry 0; SUBSCRIBE and PUBLISH include MQTT5 property length fields; PUBACK includes MQTT5 reason/properties; inbound PUBLISH parsing skips MQTT5 properties. Added retained dynamic state expiry equal to RuntimeConfig.CapabilityTTL for capability state, MCP status, and video status, while descriptors remain retained without expiry. Validated with just unit::daemon::test.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Unit daemon MQTT now uses MQTT5 packet shapes for connect/subscribe/publish/puback and inbound publish parsing. Dynamic retained board-owned state topics carry broker-side message expiry from the configured capability TTL; retained MCP/video descriptors remain unexpired. Focused tests cover MQTT5 packet encoding/parsing and retained expiry policy, and just unit::daemon::test passes.
<!-- SECTION:FINAL_SUMMARY:END -->
