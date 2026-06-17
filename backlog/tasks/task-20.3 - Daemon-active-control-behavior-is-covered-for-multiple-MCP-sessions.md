---
id: TASK-20.3
title: Daemon active-control behavior is covered for multiple MCP sessions
status: Done
assignee:
  - '@codex'
created_date: '2026-06-17 07:12'
updated_date: '2026-06-17 07:52'
labels: []
milestone: multi-user device observation
dependencies: []
references:
  - devices/unit/daemon/internal/daemon/runtime.go
  - devices/unit/daemon/internal/daemon/runtime_test.go
  - devices/unit/aws/mcp-shadow.schema.json
documentation:
  - >-
    backlog/docs/architecture/multi-user-device-observation/doc-19 -
    Multi-user-device-observation-architecture.md
  - >-
    backlog/docs/milestones/multi-user-device-observation/doc-20 -
    Milestone-multi-user-device-observation.md
modified_files:
  - devices/unit/daemon/internal/daemon/runtime_test.go
  - devices/unit/aws/mcp-shadow.schema.json
  - devices/unit/aws/default-mcp-shadow.json
  - devices/unit/docs/board-video.md
  - devices/unit/docs/thing-shadow.md
  - docs/contracts/unit-device-contracts.md
parent_task_id: TASK-20
ordinal: 42000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Multiple MCP sessions can perform read-only state calls without becoming active controller.
- [x] #2 A non-owner MCP session cannot execute actuator tools without explicit takeover.
- [x] #3 Explicit takeover switches active owner and epoch, stops previous motion, and prevents the old epoch from continuing control.
- [x] #4 The MCP shadow/schema/docs describe the active-control status consumed by Office.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect daemon MCP active-control state, JSON-RPC tool handling, status publication, current tests, and the MCP shadow schema/docs.
2. Preserve existing MCP topics and actuator semantics while covering multi-session read-only behavior, non-owner actuator rejection, takeover, epoch switch, and stop-on-takeover.
3. Add or update daemon tests against runtime behavior rather than only source strings.
4. Update MCP shadow schema/docs only as needed to document activeControl status consumed by Office.
5. Run focused daemon/schema validation and broader affected tests; record rollout notes before closing.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented daemon active-control coverage and active-control status contract documentation.

Changes made:
- Added TestMCPMultiSessionActiveControlPolicy to exercise two MCP sessions through the daemon IPC path. It verifies read-only robot.get_state/control.get_state do not acquire active control, non-owner cmd_vel.publish is rejected and does not touch hardware, active-owner publish delegates to hardware, explicit takeover switches active session and epoch, takeover stops prior motion, retained MCP status reports the new owner, and the previous owner/old epoch cannot continue control.
- Added test helpers to read MCP structuredContent and the latest retained MCP status message.
- Updated devices/unit/aws/mcp-shadow.schema.json and default-mcp-shadow.json to document/default status.activeControl.
- Updated devices/unit/docs/board-video.md, devices/unit/docs/thing-shadow.md, and docs/contracts/unit-device-contracts.md with activeControl status shape and observer/takeover semantics.

Validation:
- gofmt -w devices/unit/daemon/internal/daemon/runtime_test.go: pass.
- jq empty devices/unit/aws/mcp-shadow.schema.json devices/unit/aws/default-mcp-shadow.json: pass.
- python3 schema/default inspection: pass; activeControl type is [object,null], required fields are sessionId/transport/sinceMs/expiresAtMs/epoch, and default activeControl is null.
- GOTMPDIR=/Users/Maxim/Developer/txing/tmp/gotmp GOMAXPROCS=2 go test ./internal/daemon -run TestMCPMultiSessionActiveControlPolicy -count=1 -v: pass.
- GOTMPDIR=/Users/Maxim/Developer/txing/tmp/gotmp GOMAXPROCS=2 go test ./internal/daemon: pass.

Validation note:
- Test binaries executed from /private/tmp/ram were killed with signal 137 before Go init. Rebuilding/running with GOTMPDIR inside the workspace fixed execution and produced the passing daemon results above.

Rollout:
- No daemon runtime code or firmware changed. Test/docs/schema/default updates ship through normal repository review. If publishing updated type contracts, use the normal shared AWS type-catalog/deployment flow; no AWS mutation was run here.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-20.3 complete. Daemon tests now cover multi-session MCP observer/control policy, takeover, epoch protection, and retained MCP active-control status; schema/default/docs now describe the activeControl status consumed by Office.
<!-- SECTION:FINAL_SUMMARY:END -->
