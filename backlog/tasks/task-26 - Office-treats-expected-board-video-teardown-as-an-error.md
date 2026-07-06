---
id: TASK-26
title: Office treats expected board video teardown as an error
status: Done
assignee:
  - '@claude'
created_date: '2026-07-05 15:44'
updated_date: '2026-07-06 04:39'
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
- [x] #1 Office-commanded REDCON transitions out of level 1 and daemon-driven worker stop/restart cycles do not surface an MCP data channel error event in office.
- [x] #2 A data channel closure while the device still reports video ready continues to surface as a visible error.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Root cause: the shared board RTC session treated every data channel close as a viewer failure (closePeer notify with a generic error event), and the dedicated device video route stays mounted regardless of REDCON, so office-commanded transitions and supervised worker stops always produced the 'MCP WebRTC data channel closed' feed entry. Fix: closures are now classified at the source. A clean remote data channel close - the shape produced by a commanded REDCON transition or a supervised SIGTERM worker stop - emits a new non-error 'ended' viewer event; the panel shows 'Board video ended by the device' and nothing reaches the runtime-error feed (the report effect only fires for status error). Unclean transport loss (connection failed/disconnected, data channel error, signaling and offer/answer failures) keeps the error classification and the feed entry, which is exactly the shape a worker crash produces. Changes: ViewerUiState/ViewerUiEvent gained the ended state in both the facade (video-session.ts) and the runtime (video-session-runtime.ts), closePeer takes a cause, the data channel close listener passes ended, VideoPanel labels the ended state. Reducer test added; 169/169 office tests pass, tsc clean; the single lint error is the pre-existing cmd-vel-teleop.ts unused-variable issue outside this change. Live drills pending.

Drill round 1 found a daemon-side bug the office change exposed: commanding 2 from REDCON 1 showed the new 'Board video ended by the device' label with no feed entry (office behavior correct), but reported REDCON stuck at 1 with a frozen last frame. Cause: the worker's KVS teardown exceeded the 5s SIGTERM grace (viewer connected, TURN/signaling teardown), so supervision SIGKILLed it before the worker's own STOPPED bridge report went out, and the daemon's video state stayed ready - capability video:true kept derived REDCON at 1. The earlier 22.5 drills passed only because teardown happened to finish inside the grace window. Fix in the mac daemon supervisor (worker.go): supervision now always emits the VideoWorkerStopped event itself once the supervised worker is confirmed gone (deferred on every supervision exit path), so video readiness drops regardless of how the worker died; supervisor test updated to require exactly one stopped event and no error on supervised stops. Mac daemon suites pass; daemon rebuilt and restarted. Both drills pending re-run.

Drill round 2: commanded 1->2 worked (label shown, REDCON dropped to 2 after the supervisor fix) but a 'Board RTC connection disconnected' feed entry appeared ~10s after the command: closure-shape classification alone is racy, because a SIGTERMed worker stops media before its SCTP close reliably reaches the browser, so the ICE timeout ('disconnected', classified failure) can win the race against the clean channel close ('ended'). Second fix, state-aware: the office video route's onRuntimeError now consults the live shadow-reported REDCON through the adapter's canUseBoardVideo gate and drops the feed entry when the device has already left its video-capable posture (the panel still shows the non-streaming state); closures while the device still reports REDCON 1 keep surfacing, which is AC 2's case. reportedRedcon==null (shadow not yet loaded) never suppresses. tsc clean, 169/169 office tests pass. AC2 drill needs a closure while the device still reports ready: freeze the worker with SIGSTOP (daemon keeps seeing it alive) rather than kill -9 (which degrades REDCON within seconds and correctly quiets the browser-side entry).

User confirmed all functionality after the final drill round: the commanded 1->2 transition produces no notification feed entry (either the clean 'ended' close or the state-suppressed trailing ICE disconnect), reported REDCON drops to 2, and a transport failure while the device still reports REDCON 1 (worker frozen with SIGSTOP) still surfaces the feed error; the subsequent kill -9 recovery was caught by supervision (daemon log 20:21:41Z, restart within 1s) with video recovering automatically. Daemon-side companion fixes shipped along the way: supervision emits the stopped video event itself once the worker is confirmed gone (worker.go), covering SIGKILL-after-grace teardowns.

User found a residual case after closing: commanding REDCON 4 from 1 produced 'Board RTC connection disconnected' 12s after the command (2026-07-06 04:31Z). The reported-state gate lost the race from the other side - a command out of REDCON 1 blocks in the daemon behind the worker teardown (SIGTERM grace + SIGKILL, up to ~13s) before the new capability state even publishes, so the browser's ICE timeout can fire while the shadow still reports REDCON 1. Fix: the suppression now also consults office's own in-flight command - shouldSuppressBoardVideoRuntimeError (device-adapter.ts, unit-tested) drops the feed entry when pendingTargetRedcon targets a non-video level (office commanded the teardown itself, mirroring the shouldSuppressRobotStateTeardownError precedent) or when the reported REDCON has already left the video-capable posture; unknown shadow state and commands into video never suppress. tsc clean, 170/170 office tests. Re-validation of the 1->4 path pending (browser refresh required).

User confirmed the commanded 1->4 path live: feed stays clean with the pending-command gate in place. All expected-teardown shapes are now quiet (clean channel close, ICE timeout after convergence, ICE timeout during a blocked out-of-video command) while failures with the device still offering video keep surfacing.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Office no longer flags expected board video teardown as an error. Two layers: (1) the shared board RTC session classifies a clean remote MCP data channel close as a non-error 'ended' viewer state (panel shows 'Board video ended by the device', nothing reaches the notification feed) while transport failures, signaling errors, and channel errors stay errors; (2) because a SIGTERMed worker's teardown races the browser's ICE timeout, the video route additionally gates feed entries on live device state - a closure reported after the shadow-reported REDCON has left the adapter's video-capable posture is dropped as the trailing edge of an expected teardown, while closures with the device still reporting video (validated with a SIGSTOP-frozen worker) keep surfacing. A daemon-side gap found during the drills was fixed in the mac supervisor: it now emits the stopped video event itself once the supervised worker is confirmed dead, so REDCON drops even when the worker is SIGKILLed before its own STOPPED bridge report. Validated live on mac-rcg3rg with user confirmation. Applies to all board-video device types (unit and mac). Rollout: office ships with the next Cloudflare Pages deploy; the mac daemon fix is dev-local (just mac::restart from the user's terminal).
<!-- SECTION:FINAL_SUMMARY:END -->
