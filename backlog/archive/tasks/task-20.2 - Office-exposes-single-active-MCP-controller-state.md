---
id: TASK-20.2
title: Office exposes single active MCP controller state
status: Done
assignee:
  - '@codex'
created_date: '2026-06-17 07:11'
updated_date: '2026-06-17 07:40'
labels: []
milestone: multi-user device observation
dependencies: []
references:
  - office/src/shadow-api-runtime.ts
  - office/src/shadow-api.ts
  - devices/unit/web/TxingPanel.tsx
documentation:
  - >-
    backlog/docs/architecture/multi-user-device-observation/doc-19 -
    Multi-user-device-observation-architecture.md
  - >-
    backlog/docs/milestones/multi-user-device-observation/doc-20 -
    Milestone-multi-user-device-observation.md
modified_files:
  - office/src/App.tsx
  - office/src/shadow-api.ts
  - office/src/shadow-api-runtime.ts
  - office/src/index.css
  - devices/unit/web/TxingPanel.tsx
  - office/test/app-source.test.ts
  - office/test/shadow-api-runtime.test.ts
  - office/test/txing-panel.test.tsx
parent_task_id: TASK-20
ordinal: 41000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Office distinguishes no active MCP owner, current-browser owner, and another-session owner for MCP-capable devices.
- [x] #2 Observer sessions cannot drive before ownership is known or while another MCP session owns active control.
- [x] #3 Explicit takeover sends control.activate with takeover true and then enables control only after the current browser owns the active MCP session.
- [x] #4 MCP actor metadata identifies the signed-in user rather than a static browser label.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the Office MCP active-control state model, runtime activate/takeover path, and unit panel rendering to identify what already distinguishes unknown/no-owner/current/other-owner states.
2. Preserve the single active MCP session contract and avoid REDCON/Sparkplug changes; scope UI changes to MCP-capable device control affordances.
3. Ensure observer sessions cannot drive until ownership is positively known as current-browser ownership, including the no-state/unknown startup window.
4. Send takeover requests with takeover true and expose signed-in actor metadata from the authenticated session instead of a static browser label.
5. Add focused tests for state distinctions, disabled observer input, takeover activation, and actor metadata, then run Office validation.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented Office MCP active-control ownership as an explicit UI/runtime state. App now derives unknown/no-owner/current-browser/another-session ownership and only enables keyboard drive when ownership is current-browser. Unit panel now renders distinct active-control pending/current states and explicit take-control buttons for no-owner and another-session states. Shadow sessions now carry an mcpActor derived from the signed-in Office user (email, then name, then sub) and control.activate uses that actor instead of the static txing-web label. Runtime also consumes retained/live MCP status activeControl payloads to update owner visibility and caller ownership when possible. REDCON/Sparkplug commandability was not changed.

Validation:
- cd office && bun test test/txing-panel.test.tsx test/shadow-api-runtime.test.ts test/app-source.test.ts: 22 pass.
- cd office && bun run build: pass.
- cd office && bun test: 154 pass.
- cd office && ./node_modules/.bin/eslint src/App.tsx src/shadow-api.ts src/shadow-api-runtime.ts test/txing-panel.test.tsx test/shadow-api-runtime.test.ts test/app-source.test.ts: pass.
- cd office && bun run lint: blocked by pre-existing unrelated office/src/cmd-vel-teleop.ts:40 unused _repeat lint error.

Rollout:
- Office changes roll out through the normal Cloudflare Pages Git deployment.
- No AWS infrastructure, REDCON, Sparkplug, or firmware deployment is required for this task.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-20.2 complete. Office now exposes explicit MCP active-control ownership states, blocks observer drive input until the current browser owns active control, sends explicit takeover activation with takeover=true, and identifies the MCP actor from the signed-in user instead of a static browser label.
<!-- SECTION:FINAL_SUMMARY:END -->
