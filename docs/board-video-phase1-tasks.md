# Board Video MVP Tasks

This checklist tracks only the simplified local MVP:

- headless board
- local Vite dev server on the Mac
- direct IPv6 WebRTC session
- GStreamer rswebrtc only
- no auth, TLS, MediaMTX, or cloud upload

## 1. Contracts and Docs

- [x] Replace the earlier MediaMTX/TLS design doc with the simplified MVP design
- [x] Update `docs/txing-shadow.schema.json` with optional `reported.board.video.*`
- [x] Update `docs/thing-shadow.md` with the new `board.video` fields
- [x] Lock the MVP status enum to `starting | ready | error`
- [x] Lock the MVP local fields to `signallingUrl` and `streamName`

## 2. Board Runtime Split

- [x] Add a dedicated `txing-board-media` service under `board/`
- [x] Define the runtime file contract at `/run/txing/board-media/state.json`
- [x] Keep `txing-board-media` out of AWS IoT publishing
- [x] Keep `txing-board` as the only publisher of `board.*`

## 3. Media Serving

- [x] Use GStreamer rswebrtc directly for the MVP
- [x] Configure `webrtcsink` with built-in signaling and no embedded web server
- [x] Fix the stream metadata name to `board-cam`
- [x] Publish the direct signaling URL as `ws://[<board-ipv6>]:8443`
- [x] Keep the publisher H.264-oriented and overrideable through `--source-pipeline`

## 4. Web Integration

- [x] Add `gstwebrtc-api` to the local web app
- [x] Read `board.video.local.signallingUrl` and `streamName` from shadow
- [x] Add a minimal video panel to the signed-in UI
- [x] Connect to the board over rswebrtc from the Vite dev app
- [x] Keep the MVP single-viewer and local-dev-only

## 5. Explicitly Deferred

- [ ] auth
- [ ] TLS
- [ ] MediaMTX
- [ ] browser-to-board control transport
- [ ] `kvssink`
- [ ] cloud upload
