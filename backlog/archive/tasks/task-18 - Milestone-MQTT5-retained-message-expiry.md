---
id: TASK-18
title: 'Milestone: MQTT5 retained message expiry'
status: Done
assignee: []
created_date: '2026-05-30 08:17'
updated_date: '2026-05-30 10:05'
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
modified_files:
  - docs/sparkplug-lifecycle.md
ordinal: 31000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Repository-owned MQTT client sessions that connect directly to AWS IoT use MQTT 5 explicitly without changing public topics or payload schemas.
- [x] #2 Dynamic retained unit board state topics expire at the configured capability TTL while descriptor topics remain retained without expiry.
- [x] #3 Rig startup and reconnect behavior can consume retained board capability state for inventoried devices through exact subscriptions.
- [x] #4 Validation covers unit daemon, rig, office MQTT paths, and confirms shared AWS Python has no MQTT client surface.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Milestone closure audit confirmed all subtasks TASK-18.1 through TASK-18.4 are Done. Documentation is consistent with the MQTT5 retained-message-expiry scope: unit daemon and rig own real MQTT client sessions, office already uses MQTT5, shared AWS Python has no MQTT client surface, and Go runtime Lambdas use IoT Rules / IoT Data Plane APIs rather than persistent MQTT client sessions. Added a Sparkplug lifecycle note documenting that transient local sparkplug=false samples do not override a still-fresh sparkplug=true sample before the manager TTL, matching the post-MQTT5 flapping fix. Validation evidence is recorded on subtasks: just unit::daemon::test, just rig::test, shared AWS Python pytest, and cd office && bun test.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Milestone complete. MQTT5 is explicit for repository-owned AWS IoT MQTT client sessions, dynamic retained unit board state expires at the configured capability TTL, descriptor retained topics remain unexpired, rig retained board-state replay uses exact per-device subscriptions, shared AWS Python has no MQTT client path, office MQTT5 flow is guarded, and durable docs now include retained-message rollout notes plus the transient Sparkplug offline suppression rule.
<!-- SECTION:FINAL_SUMMARY:END -->
