---
id: TASK-22.3
title: mac daemon action layer reaches REDCON 2 with board and MCP stub
status: To Do
assignee: []
created_date: '2026-07-03 07:45'
labels: []
milestone: m-1
dependencies:
  - TASK-22.2
references:
  - devices/unit/daemon/internal/daemon
  - devices/unit/proto/txing/unit/board_video/v1/board_video.proto
  - docs/contracts/board-video-bridge.md
  - devices/unit/docs/board-video.md
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 52000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add the action-layer role to txing-mac-daemon: at simulated power-on it connects to AWS IoT with the device certificate, publishes retained board capability state, video and MCP descriptor/status topics, and board/mcp/video named-shadow updates following the unit daemon contracts; serves the BoardVideoBridge gRPC socket; and answers a read-only MCP stub (robot.get_state, control.get_state, no actuator tools) over mqtt-jsonrpc sessions. Video stays declared but unavailable in this task.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Commanding REDCON 2 from office converges the mac device to reported REDCON 2 with board and mcp capabilities true and video false, and commanding REDCON 4 returns it to sleep with board evidence purged.
- [ ] #2 Commanding REDCON 1 is accepted and converges to reported REDCON 2 while no video worker exists.
- [ ] #3 Retained cloud topics and named shadows follow the unit daemon shapes and expiry policy, using a client id distinct from the rig-owned device session, and go offline cleanly on daemon shutdown.
- [ ] #4 The office device panel can call the read-only MCP tools at REDCON 2 and receives stub state; actuator tools are absent from the tool list.
<!-- AC:END -->
