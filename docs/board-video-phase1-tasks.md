# Board Video MVP Tasks

This checklist tracks the plain-AWS-WebRTC phase-1 plan.

- headless board
- one live operator path through plain AWS WebRTC signaling
- no HLS/DASH as the live control path
- no WebRTC ingestion/storage or multiviewer in phase 1
- directional operator control, not precision teleoperation
- field tests may still reopen a second direct operator path later

## 1. Contracts and Docs

- [x] Replace the old local-MediaMTX phase-1 design with the plain-AWS-WebRTC design
- [x] Update `docs/thing-shadow.md` to describe the plain-AWS-WebRTC phase-1 contract and mark old local fields as compatibility-only
- [x] Update `docs/txing-shadow.schema.json` to support the AWS-WebRTC transport/session shape
- [x] Document the phase-1 field-test rule: direct operator video is deferred unless field tests justify it

## 2. Board Runtime

- [x] Keep `txing-board` as the only publisher of `board.*`
- [x] Decide whether the board owns the plain AWS WebRTC master session directly or supervises a dedicated sender
- [x] Implement a dedicated `board.video_sender` state manager that launches the actual native sender command
- [x] Publish `board.video.transport=aws-webrtc`
- [x] Publish `board.video.session.*` metadata for browser/native clients
- [x] Gate `board.video.ready` on supervised sender readiness, not a board-local iframe endpoint
- [x] Surface coarse sender failures through `board.video.lastError`
- [x] Track best-effort `board.video.viewerConnected` from supervised sender output markers
- [x] Avoid a repo-managed `kvssink`-based sender path

## 3. Operator Integration

- [x] Replace the board-local iframe viewer approach with a plain AWS WebRTC viewer path
- [x] Keep board motion control out of the media path and continue using `txing/board/cmd_vel`
- [ ] Keep the initial operator scope to one human operator
- [ ] Allow the same phase-1 design to expand to native iOS/Android clients later

## 4. ML / Cloud Consumption

- [x] Keep ML and other cloud-side consumers out of the phase-1 media path
- [ ] Define a separate follow-on cloud consume path if ML needs media later
- [x] Do not make low-latency ML a blocker for the operator path

## 5. Field Tests

- [ ] Measure `p95` operator glass-to-glass latency against the `800 ms` target
- [ ] Measure jitter and short-stall behavior on target links
- [ ] Validate practical operator quality for directional commands
- [ ] Revisit the direct operator path only if field tests fail the plain-AWS-WebRTC design

## 6. Explicitly Deferred

- [ ] HLS/DASH as the operator control path
- [ ] WebRTC ingestion/storage
- [ ] multiviewer
- [ ] recording as a requirement
- [ ] low-latency ML as a requirement
- [ ] a second direct device-to-operator video path unless field tests justify it
