---
id: TASK-22.5
title: mac device reaches REDCON 1 with office-visible video
status: To Do
assignee: []
created_date: '2026-07-03 07:45'
labels: []
milestone: m-1
dependencies:
  - TASK-22.3
  - TASK-22.4
references:
  - docs/sparkplug-lifecycle.md
  - devices/unit/docs/board-video.md
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
  - >-
    backlog/docs/milestones/mac-device-type/doc-24 -
    Milestone-Mac-device-type.md
parent_task_id: TASK-22
priority: high
ordinal: 54000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Wire worker supervision into txing-mac-daemon (spawn at REDCON 1, restart with backoff, SIGTERM on leaving 1 so the camera is only active at REDCON 1), gate the video capability on worker readiness reported over the bridge, and validate the full e2e flow including failure drills (worker crash at REDCON 1, rig restart, daemon kill at REDCON 1). Document the per-device registration runbook and mac client operation in the device README.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Commanding REDCON 1 from office converges the device to reported REDCON 1 and the office video route shows live Mac camera video; commanding REDCON 2 stops the stream and the camera indicator turns off.
- [ ] #2 Killing the worker at REDCON 1 degrades reported REDCON to 2 with a visible video error and the daemon recovers the stream without manual steps.
- [ ] #3 Stopping the daemon at REDCON 1 results in DDEATH within the capability TTL with no stale ready video status left behind.
- [ ] #4 The registration and operation runbook is documented and was followed end-to-end on a real mac device registration.
<!-- AC:END -->
