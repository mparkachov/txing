---
id: TASK-20.1
title: Office supports multi-user observation across device types
status: Done
assignee:
  - '@codex'
created_date: '2026-06-17 07:11'
updated_date: '2026-06-17 07:23'
labels: []
milestone: multi-user device observation
dependencies: []
references:
  - office/src/App.tsx
  - office/src/device-adapter.ts
documentation:
  - >-
    backlog/docs/architecture/multi-user-device-observation/doc-19 -
    Multi-user-device-observation-architecture.md
  - >-
    backlog/docs/milestones/multi-user-device-observation/doc-20 -
    Milestone-multi-user-device-observation.md
modified_files:
  - office/test/shadow-client-id.test.ts
  - office/test/device-registry.test.ts
  - office/test/app-source.test.ts
parent_task_id: TASK-20
ordinal: 40000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Two signed-in browser sessions can open the same AWS device and receive the same current shadow-derived state.
- [x] #2 Registered device types without MCP active control remain multi-user view-only with no actuator-control affordance.
- [x] #3 REDCON panel commandability and publish behavior remain governed only by the existing Sparkplug rules.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the current Office route/device adapter flow and tests for assumptions that only unit/bot detail routes can be observed concurrently.
2. Keep REDCON handling unchanged and add tests that lock the Sparkplug panel commandability path to existing rules.
3. Ensure registered non-MCP device adapters remain view-only by exercising their detail rendering/state path without actuator-control affordances.
4. Add or update Office tests proving two browser-style sessions can create independent shadow/MQTT client identities and observe the same device state without client-id collision.
5. Run the focused Office tests, then the broader Office test suite if the touched surface warrants it; record validation and rollout notes before closing the task.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented as focused Office regression coverage. No runtime code changes were required after inspection: the existing shadow MQTT client ID helper already supports independent browser sessions, non-MCP adapters already opt out of drive/video control, and REDCON commandability is already governed by Sparkplug wiring. Added tests for two browser-style sessions on the same identity, registered non-MCP device detail panels remaining view-only across cloud-mcu/weather/power, and REDCON controls staying independent from MCP control state.

Validation:
- cd office && bun test test/shadow-client-id.test.ts test/device-registry.test.ts test/app-source.test.ts: 17 pass.
- cd office && ./node_modules/.bin/eslint test/shadow-client-id.test.ts test/device-registry.test.ts test/app-source.test.ts: pass.
- cd office && bun test: 149 pass.
- cd office && bun run lint: blocked by pre-existing unrelated office/src/cmd-vel-teleop.ts:40 unused _repeat lint error.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-20.1 complete. Office now has regression coverage for multi-user same-device observation via distinct browser session MQTT client IDs, view-only behavior for registered non-MCP device types, and REDCON commandability remaining Sparkplug-only rather than MCP-control-gated.
<!-- SECTION:FINAL_SUMMARY:END -->
