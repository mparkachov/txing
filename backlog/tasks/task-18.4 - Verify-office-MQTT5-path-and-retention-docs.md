---
id: TASK-18.4
title: Verify office MQTT5 path and retention docs
status: Done
assignee:
  - '@codex'
created_date: '2026-05-30 08:17'
updated_date: '2026-05-30 09:33'
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
modified_files:
  - office/test/shadow-api-runtime.test.ts
  - docs/components/board.md
  - devices/unit/docs/board-video.md
parent_task_id: TASK-18
ordinal: 35000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Office tests continue to verify that the browser live-shadow, Sparkplug command, and MCP MQTT paths use the existing MQTT5 client flow.
- [x] #2 Durable board/unit documentation records which retained topics expire and which descriptor topics remain unexpired.
- [x] #3 Rollout notes explain that old retained messages without expiry are replaced only by same-topic republishes and may need manual cleanup if orphaned.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect office MQTT5 runtime/tests and durable board/unit documentation.
2. Add or adjust office tests if live-shadow, Sparkplug command, or MCP MQTT5 flows are not explicitly covered.
3. Update durable retained-message docs with expiring vs non-expiring topics and rollout cleanup notes.
4. Run office tests and any relevant documentation-adjacent tests.
5. Check acceptance criteria, record evidence, and close TASK-18.4.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added an office runtime source guard that verifies the browser shadow runtime keeps the AWS CRT MQTT5 websocket builder/client, live-shadow publish packets, Sparkplug DCMD publishes, and MCP MQTT subscribe/publish packets on mqtt5 packet types. Updated durable board docs to identify expiring dynamic retained topics, unexpired descriptor topics, and retained-message cleanup behavior for old/orphaned topics. Validation: cd office && bun test -> 137 pass, 0 fail.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Office MQTT5 browser runtime path is now explicitly guarded by tests, and board/unit documentation records retained topic expiry policy plus rollout cleanup notes. Validation: cd office && bun test -> 137 pass, 0 fail.
<!-- SECTION:FINAL_SUMMARY:END -->
