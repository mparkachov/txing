---
id: TASK-26
title: Office treats expected board video teardown as an error
status: To Do
assignee: []
created_date: '2026-07-05 15:44'
labels: []
dependencies: []
references:
  - office/src/video-session-runtime.ts
priority: medium
ordinal: 63000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The shared board RTC session in office (video + MCP data channel over KVS WebRTC) registers a close listener on the MCP data channel that always calls closePeer(true, 'MCP WebRTC data channel closed'), which emits an error UI event to every video consumer. When office itself tears the session down (panel closed, video route left) closePeer(false) keeps it silent, but when the remote side ends the session - which is exactly what happens after an office-commanded REDCON transition out of level 1, or when the daemon stops or restarts the worker - the browser fires the data channel close event first and office reports 'MCP WebRTC data channel closed' as an error even though the closure is the expected consequence of the commanded transition. Observed with mac-rcg3rg during standard office-driven REDCON drills (2026-07-05) and previously with unit devices; not device-specific. Proposed direction: treat a remote data channel close as informational session-ended when the device's reported video readiness or REDCON no longer offers video (or when a lower REDCON command was just issued from this session), and keep the error surface for closures that happen while video is still supposed to be live.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Office-commanded REDCON transitions out of level 1 and daemon-driven worker stop/restart cycles do not surface an MCP data channel error event in office.
- [ ] #2 A data channel closure while the device still reports video ready continues to surface as a visible error.
<!-- AC:END -->
