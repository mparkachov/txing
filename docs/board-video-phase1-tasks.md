# Board Video MVP Tasks

This checklist tracks only the simplified local MVP:

- headless board
- local Vite dev server on the Mac
- direct local-LAN access to the board
- MediaMTX `rpiCamera` hardware H.264 encode on the board
- MediaMTX as the separate browser-ready WebRTC server
- no auth, TLS, browser-to-board control transport, or cloud upload

## 1. Contracts and Docs

- [x] Replace the earlier rswebrtc MVP design doc with the MediaMTX MVP design
- [x] Update `docs/txing-shadow.schema.json` with `reported.board.video.local.viewerUrl` and `streamPath`
- [x] Update `docs/thing-shadow.md` with the new `board.video` fields
- [x] Lock the MVP status enum to `starting | ready | error`
- [x] Lock the MVP local fields to `viewerUrl` and `streamPath`

## 2. Board Runtime Split

- [x] Keep `txing-board` as the only publisher of `board.*`
- [x] Probe MediaMTX directly inside `txing-board`
- [x] Gate the first board shadow publish on MediaMTX readiness
- [x] Keep `mediamtx` as the separate operator-managed media service

## 3. Media Serving

- [x] Replace `webrtcsink` with MediaMTX camera ownership
- [x] Keep the camera source locked to `1920x1080` at `30 fps`
- [x] Fix the MediaMTX stream path to `board-cam`
- [x] Publish the iframe URL as `http://<board-ipv4>:8889/board-cam/`
- [x] Keep hardware H.264 inside MediaMTX `rpiCamera`

## 4. Web Integration

- [x] Remove `gstwebrtc-api` from the local web app
- [x] Read `board.video.local.viewerUrl` and `streamPath` from shadow
- [x] Keep the board video panel in the signed-in UI
- [x] Load the MediaMTX viewer page in an iframe from the Vite dev app
- [x] Keep the MVP single-viewer and local-dev-only

## 5. Explicitly Deferred

- [ ] auth
- [ ] TLS
- [ ] browser-to-board control transport
- [ ] `kvssink`
- [ ] cloud upload
