# Board Video Phase 1 Tasks

This checklist tracks only the agreed phase 1 scope:

- headless local browser video
- `txing-board` as the single `board.*` shadow publisher
- shadow-published read token for browser stream authentication
- no `kvssink` implementation yet

## 1. Contracts and Docs

- [ ] Review and approve `docs/board-video-phase1-design.md`
- [ ] Extend `docs/txing-shadow.schema.json` with optional `reported.board.video.*`
- [ ] Update `docs/thing-shadow.md` with the new `board.video` fields
- [ ] Decide the exact token field names under `board.video.local.auth`
- [ ] Decide the exact `status` enum for `board.video.status`

## 2. Board Runtime Split

- [ ] Add a dedicated `txing-board-media` service under `board/`
- [ ] Define the local runtime file contract at `/run/txing/board-media/state.json`
- [ ] Ensure `txing-board-media` never publishes to AWS IoT directly
- [ ] Keep `txing-board` as the only publisher of `board.*`

## 3. Media Serving

- [ ] Package and configure MediaMTX as a board-local service
- [ ] Pick the local publish protocol from GStreamer to MediaMTX
- [ ] Build the board camera publisher around a low-latency H.264 path
- [ ] Confirm the path naming convention for the local stream
- [ ] Expose a network WebRTC/WHEP read endpoint on the board

## 4. Authentication

- [ ] Implement token generation inside `txing-board-media`
- [ ] Rotate the token on media-service restart
- [ ] Implement the local HTTP auth endpoint used by MediaMTX
- [ ] Restrict accepted auth to read-only WebRTC access on the configured path
- [ ] Write token metadata into `/run/txing/board-media/state.json`
- [ ] Mirror token metadata into the Thing Shadow through `txing-board`

## 5. Board Shadow Integration

- [ ] Teach `txing-board` to read `/run/txing/board-media/state.json`
- [ ] Merge `board.video` into the existing reported board payload
- [ ] Add `viewerConnected` and `lastError` reporting
- [ ] Tighten board IPv6 refresh so direct reader URLs are not stale after network changes

## 6. Web Integration

- [ ] Add a video section in `web/`
- [ ] Read `board.wifi.ipv6` and `board.video.local.*` from shadow
- [ ] Build the board-local WHEP URL from shadow metadata
- [ ] Send `Authorization: Bearer <token>` when opening the reader session
- [ ] Render connection states: unavailable, connecting, live, error
- [ ] Handle token rotation and stale shadow data cleanly

## 7. Deployment and TLS

- [ ] Choose how the board-local HTTP endpoint gets a browser-acceptable TLS certificate
- [ ] Document the network ports exposed by MediaMTX for phase 1
- [ ] Ensure the admin browser can route to the board IPv6 address
- [ ] Verify that shadow read access is limited to the intended admin identities

## 8. Validation

- [ ] Verify stream startup after a clean board boot
- [ ] Verify recovery after `txing-board-media` restart
- [ ] Verify that a restarted media service rotates the token
- [ ] Verify that a stale token is rejected by MediaMTX auth
- [ ] Verify shadow state when camera pipeline fails
- [ ] Verify shadow state when the board loses network and reconnects
- [ ] Measure click-to-first-frame latency from the web app

## 9. Explicitly Deferred

- [ ] `kvssink` cloud upload branch
- [ ] browser-to-board control transport
- [ ] per-session auth tokens
- [ ] audio
- [ ] multi-viewer policy
