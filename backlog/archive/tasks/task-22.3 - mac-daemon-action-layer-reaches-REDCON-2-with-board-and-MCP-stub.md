---
id: TASK-22.3
title: mac daemon action layer reaches REDCON 2 with board and MCP stub
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 07:45'
updated_date: '2026-07-06 10:55'
labels: []
milestone: m-1
dependencies: []
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
- [x] #1 Commanding REDCON 2 from office converges the mac device to reported REDCON 2 with board and mcp capabilities true and video false, and commanding REDCON 4 returns it to sleep with board evidence purged.
- [x] #2 Commanding REDCON 1 is accepted and converges to reported REDCON 2 while no video worker exists.
- [x] #3 Retained cloud topics and named shadows follow the unit daemon shapes and expiry policy, using a client id distinct from the rig-owned device session, and go offline cleanly on daemon shutdown.
- [x] #4 The office device panel can call the read-only MCP tools at REDCON 2 and receives stub state; actuator tools are absent from the tool list.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented internal/action in the mac daemon module: a copied-and-trimmed unit-daemon action layer (no hardware worker, no actuator MCP, no CloudWatch; stdlib + grpc/protobuf only, versions pinned to the unit daemon's). Components: MQTT5 publisher and packet codec, unit-shape topics/payloads (adapterId dev.txing.mac.DaemonBoard, serverInfo txing-mac-daemon), IoT role-alias credential fetcher (stdlib TLS), BoardVideoBridge gRPC server against the shared proto (vendored generated stubs), read-only MCP stub (initialize, tools/list, control.get_state, robot.get_state; actuator calls rejected; webrtc transport gate kept for the video milestone), video runtime state, and a session runtime with online/offline publications, 60s capability heartbeat, 5s video status ticker, and MQTT reconnect. Lifecycle: action.Controller started at targets 2/1 and stopped synchronously (offline publications first) before the watch layer publishes the lower IPC state - ordering covered by a dedicated adapter test. macconfig gained the action fields with colocated cert defaults; main.go validates the action config when present and runs watch-only with a warning otherwise.
Validation: 4/4 module test packages ok (publication contract shapes incl. retained expiry and expiresAtMs, offline all-false, video-ready capability raise + transport switch, MCP stub read-only surface, controller lifecycle, command ordering). Live with mac-rcg3rg under local-hz0ny3 (user-run cert bundle unpacked to ~/.config/txing/mac-daemon): office ladder 4->2 (Ember Watch, board+mcp true via the action MQTT session mac-rcg3rg-daemon-54215), 1 accepted and reported 2 (video declared, not ready), 4 back to Cold Camp with action layer stopped before the sleep state; user-confirmed expected behavior throughout.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The mac daemon now runs the full action layer at REDCON 2/1: its own AWS IoT session (client id <thing>-daemon-<pid>), retained board capability state (board/mcp true, video following worker readiness), unit-shaped MCP and video descriptor/status topics and named shadows with MQTT5 expiry, the BoardVideoBridge gRPC socket ready for the KVS worker, and a read-only MCP stub with no actuator tools. Leaving REDCON 2 publishes offline states before the watch layer reports the lower level. Validated live: office ladder 4->2->1(capped at 2)->4 on mac-rcg3rg. The video milestone (22.4/22.5) plugs the KVS worker into the already-running bridge to reach REDCON 1.
<!-- SECTION:FINAL_SUMMARY:END -->
