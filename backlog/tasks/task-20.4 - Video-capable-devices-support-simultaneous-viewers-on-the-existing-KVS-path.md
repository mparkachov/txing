---
id: TASK-20.4
title: Video-capable devices support simultaneous viewers on the existing KVS path
status: In Progress
assignee:
  - '@codex'
created_date: '2026-06-17 07:12'
updated_date: '2026-06-18 17:32'
labels: []
milestone: multi-user device observation
dependencies: []
references:
  - devices/unit/docs/board-video.md
  - devices/unit/board/kvs_master/src/kvs_session_real.cpp
  - devices/unit/aws/video-shadow.schema.json
documentation:
  - >-
    backlog/docs/architecture/multi-user-device-observation/doc-19 -
    Multi-user-device-observation-architecture.md
  - >-
    backlog/docs/milestones/multi-user-device-observation/doc-20 -
    Milestone-multi-user-device-observation.md
modified_files:
  - devices/unit/docs/board-video.md
  - docs/contracts/unit-device-contracts.md
  - office/test/video-multi-viewer-contract.test.ts
  - office/src/mcp-active-control.ts
  - office/test/mcp-active-control.test.ts
  - office/src/shadow-api-runtime.ts
  - office/test/shadow-api-runtime.test.ts
  - office/src/App.tsx
  - office/src/shadow-api.ts
  - devices/unit/web/TxingPanel.tsx
  - office/test/app-source.test.ts
  - office/test/txing-panel.test.tsx
  - devices/unit/daemon/internal/daemon/runtime.go
  - devices/unit/daemon/internal/daemon/runtime_test.go
parent_task_id: TASK-20
ordinal: 43000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Video-capable devices keep the existing single AWS KVS WebRTC channel and do not add a second media path.
- [ ] #2 Two browser sessions can view the same live bot video feed during manual validation.
- [x] #3 Any viewer-count status exposed by implementation is observability only and is not used for viewer admission control.
- [x] #4 Documentation distinguishes multiple video viewers from multiple active MCP controllers.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify the existing AWS KVS/WebRTC path remains the only media path for browser viewing.
2. Inspect browser shared-session lifecycle and native KVS master concurrent-session limits for multi-viewer support.
3. Add focused regression coverage and documentation only where current evidence is weak.
4. Run targeted Office/video validation and update this task with the evidence.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Automated/documentation evidence completed:
- devices/unit/docs/board-video.md now states the supported topology: one AWS KVS signaling channel per video-capable device, one device uplink, and separate WebRTC peer sessions for viewer clients.
- docs/contracts/unit-device-contracts.md now distinguishes multiple video viewers from MCP active control.
- office/test/video-multi-viewer-contract.test.ts locks the source contract: browser runtime stays on AWS KVS VIEWER role, native txing-unit-kvs-master fans encoded frames to per-peer sessions on the same channel, and video shadow exposes viewerConnected without viewerCount admission semantics.
- Manual validation from operator: two browsers with different users reached REDCON 1 and both rendered live video from the same bot.

Operator workflow requirement clarified:
- Standard operation is one operator controlling the bot. If no active MCP controller exists, both browsers should see an active Take active control button instead of a passive No active controller status.
- The current operator can either press Take active control or start driving; the first non-zero drive command auto-acquires active control via normal control.activate.
- Explicit takeover remains available when another operator already owns active control.

Active-control issues found during manual validation:
- Pressing Take active control acquired ownership briefly, but key release sent cmd_vel.stop and released active control.
- Idle active-control ownership also expired after roughly the daemon TTL (~5 seconds) because Office did not renew after an explicit takeover unless motion commands were being sent.
- No-owner state previously showed a passive No active controller status, which left both browsers without an obvious recovery action after session loss.

Fix implemented:
- Office now schedules background control.renew_active while the current browser owns active control.
- cmd_vel.stop now stops motion without releasing active control.
- When no active owner exists, drive input is enabled and the first non-zero drive command auto-acquires active control via normal control.activate.
- The Take active control button now appears when no session owns control and when another session owns active control.
- The passive No active controller status was removed from the operator panel path.
- Teardown still sends best-effort stop plus control.release_active.

Validation run after fix:
- cd office && bun test test/mcp-active-control.test.ts test/shadow-api-runtime.test.ts test/app-source.test.ts test/video-multi-viewer-contract.test.ts
- cd office && bun test test/app-source.test.ts test/txing-panel.test.tsx test/shadow-api-runtime.test.ts test/mcp-active-control.test.ts
- cd office && bun test test/txing-panel.test.tsx test/app-source.test.ts test/shadow-api-runtime.test.ts test/mcp-active-control.test.ts
- cd office && bun test
- cd office && bun run build

Pending evidence before marking complete:
- Retest the patched Office build with two browsers: both continue seeing video, both show Take active control when no owner exists, one normal operator can drive directly when no owner exists, ownership persists while idle and after movement key release, and observer takeover remains explicit when another operator owns control.

Observer reconnect issue found during manual validation:
- Daemon video event handling cleared active MCP control whenever video readiness changed the advertised MCP transport. A new viewer refresh can cause video/discovery churn without the active operator session closing, so this reset ownership for the browser that stayed connected.
- devices/unit/daemon/internal/daemon/runtime.go now treats video transport changes as discovery-only. Active control is still cleared by explicit release, active owner session close/error, TTL expiry/watchdog handling, or offline disconnect.
- devices/unit/daemon/internal/daemon/runtime_test.go adds TestMCPActiveControlSurvivesObserverReconnectAndVideoReadinessChurn, covering owner active, observer reconnect, video readiness churn, owner still able to drive, and owner close still clearing/stopping.

Additional validation run after daemon fix:
- cd devices/unit/daemon && GOTMPDIR=/Users/Maxim/Developer/txing/tmp/gotmp go test ./internal/daemon -run 'TestMCPActiveControlSurvivesObserverReconnectAndVideoReadinessChurn|TestMCPMultiSessionActiveControlPolicy|TestVideoEventsSwitchMCPTransportAndPublishState' -count=1
- cd devices/unit/daemon && GOTMPDIR=/Users/Maxim/Developer/txing/tmp/gotmp go test ./internal/daemon -count=1
- cd office && bun test
- cd office && bun run build

Active-control diagnostic logging added after intermittent manual validation drops:
- office/src/shadow-api.ts now exposes an ActiveControlLossEvent callback on the shadow session contract.
- office/src/shadow-api-runtime.ts emits that event when the current browser loses active control because MCP status reports no owner, MCP status reports another owner, control.renew_active fails, or cmd_vel.stop cannot confirm the active session.
- office/src/App.tsx writes the event to Session Log only, scoped to the device thing name, with reason text including previous owner session/actor/epoch, next owner when known, and lease timing for no-owner status.

Additional validation run after diagnostic logging:
- cd office && bun test test/app-source.test.ts test/shadow-api-runtime.test.ts
- cd office && bun test
- cd office && bun run build

Follow-up from 2026-06-18 manual validation:
- Session Log showed MCP active control dropped because daemon status reported no owner 215ms after the browser-local active lease expiry. This indicates delayed/missed lease renewal, not a takeover by the second browser.
- office/src/mcp-active-control.ts now schedules idle active-control renewal near the start of each lease. For the current 5s daemon TTL, background renewal targets roughly 1s after acquisition instead of waiting until the final 1.5s.
- office/src/shadow-api-runtime.ts now automatically reacquires control when daemon status reports no owner and this browser was the current local owner. It keeps local ownership optimistic during the reacquire attempt, so a transient no-owner status should not immediately expose the Take active control button on the active operator browser.
- Recoverable control.renew_active failures and command-time active checks also reacquire with normal control.activate when the daemon reports no active/stale active control. Another real owner still wins; that path continues to require explicit takeover.

Additional validation run after lease renewal/reacquire fix:
- cd office && bun test test/mcp-active-control.test.ts test/shadow-api-runtime.test.ts test/app-source.test.ts
- cd office && bun test
- cd office && bun run build
<!-- SECTION:NOTES:END -->
