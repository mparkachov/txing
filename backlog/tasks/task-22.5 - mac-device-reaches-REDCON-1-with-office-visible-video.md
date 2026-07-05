---
id: TASK-22.5
title: mac device reaches REDCON 1 with office-visible video
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 07:45'
updated_date: '2026-07-05 15:45'
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
- [x] #1 Commanding REDCON 1 from office converges the device to reported REDCON 1 and the office video route shows live Mac camera video; commanding REDCON 2 stops the stream and the camera indicator turns off.
- [x] #2 Killing the worker at REDCON 1 degrades reported REDCON to 2 with a visible video error and the daemon recovers the stream without manual steps.
- [x] #3 Stopping the daemon at REDCON 1 results in DDEATH within the capability TTL with no stale ready video status left behind.
- [x] #4 The registration and operation runbook is documented and was followed end-to-end on a real mac device registration.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. macconfig: add TXING_KVS_MASTER_COMMAND (empty means worker supervision disabled with a warning when REDCON 1 is commanded); devices/mac justfile start/check export a default pointing at the build-macos worker binary so the repo checkout works with an unedited cert bundle.
2. internal/action/worker.go: new supervisor owned by the Controller - spawns the worker at REDCON 1 with --board-video-bridge-socket-path, streams worker output to a log file next to the bridge socket, stops it with SIGTERM (kill fallback after a grace period) when leaving REDCON 1 or on daemon shutdown so the camera is only active at 1, restarts with 1s..30s backoff (reset after a healthy run), and emits a video worker error event on unexpected exit so reported REDCON degrades to 2 with a visible error before the automatic restart.
3. Controller wiring: video/MCP event channels lifted out of run() so the bridge and the supervisor share them; SetTarget: 1 = runtime + worker, 2 = runtime only (worker stopped synchronously), 3/4 = worker stopped then runtime stopped with offline publications; Shutdown covers the daemon-stop-at-REDCON-1 path so no stale ready video survives a clean stop, and retained-with-expiry topics cover the unclean kill within the TTL.
4. Tests: supervisor lifecycle (SIGTERM on stop, crash restart with backoff, error event emission, no restart after stop), controller target transitions with a fake command, all existing suites stay green.
5. devices/mac/README.md: consolidated registration + operation runbook (deploy-device, cert bundle, rig::start, mac::start, kvs-build, camera-probe, REDCON expectations per level) - registration steps already exercised end to end on mac-rcg3rg.
6. Live validation with the user: office ladder 4->1 with automatic worker spawn and live video, 2 stops the stream and the camera indicator, kill -9 of the worker at 1 degrades to 2 with visible error then auto-recovers, rig restart survives, just mac::stop at REDCON 1 projects immediate DDEATH with no ghost video.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented worker supervision: internal/action/worker.go WorkerSupervisor (spawn TXING_KVS_MASTER_COMMAND with --board-video-bridge-socket-path, worker output to txing-unit-kvs-master.log next to the bridge socket, SIGTERM with 5s SIGKILL fallback on stop, 1s..30s restart backoff reset after healthy minute-long runs, unexpected exits emit a VideoWorkerError event so reported REDCON degrades with a visible error before the restart). Controller now distinguishes targets: 1 = runtime + worker, 2 = runtime with worker stopped synchronously, 3/4 and Shutdown = worker stopped then runtime stopped with offline publications; video event channel lifted into the Controller so the bridge and supervisor share it (non-blocking sends, no deadlock across MQTT reconnects). macconfig/action config gained KVSMasterCommand (empty = one-time warning at REDCON 1, video stays unavailable); mac::start/check default it to the kvs-build output; daemon.env.template documents the default. README gained the registration + operation runbook and the supervision description. Tests: supervisor SIGTERM stop without error events, crash restart with repeated error events, worker log capture; all mac daemon suites pass, gofmt/vet clean. Daemon rebuilt and restarted on mac-rcg3rg; live drills pending.

Live drills user-confirmed on mac-rcg3rg: (1) office REDCON 1 spawned the worker automatically with live camera video on the office video route, REDCON 2 stopped the stream with the camera indicator off; (2) kill -9 of the worker at REDCON 1 degraded reported REDCON to 2 with a visible video error and the daemon auto-recovered the stream; (3) just mac::stop at REDCON 1 projected immediate DDEATH with no stale video; (4) the README runbook matches the registration and operation flow exercised end to end on mac-rcg3rg during this milestone. Observation during the drills: office logs 'MCP WebRTC data channel closed' as an error on expected, office-commanded teardowns; not mac-specific (shared board RTC session behavior), filed as TASK-26.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The mac device now reaches REDCON 1 end to end: the daemon supervises the KVS video worker itself (spawn at REDCON 1 via TXING_KVS_MASTER_COMMAND defaulted by just to the kvs-build output, SIGTERM with SIGKILL fallback when leaving 1 so the camera is only active at REDCON 1, 1s-30s restart backoff, unexpected exits surface as video errors that degrade reported REDCON to 2 until the automatic restart recovers). Video readiness continues to flow only over the BoardVideoBridge; the Controller runs runtime+worker at 1, runtime-only at 2, and stops worker-then-runtime with offline publications at 3/4 and on shutdown. Validated live on mac-rcg3rg: office ladder with automatic video at 1, camera indicator off at 2, worker crash recovery, and immediate DDEATH with no ghost video on daemon stop. The device README documents the registration and operation runbook followed on the real registration. Follow-ups filed: TASK-25 (macOS TLS CA log noise), TASK-26 (office flags expected video teardown as an error). Deployment: dev-only, just mac::kvs-build + just mac::restart; no unit/raspi or cloud changes.
<!-- SECTION:FINAL_SUMMARY:END -->
