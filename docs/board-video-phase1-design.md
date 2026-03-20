# Board Video Phase 1 Design

## Status

- Scope: phase 1 only
- Goal: authenticated local browser video from the board over the board's IPv6 address
- Future requirement kept in mind: add a cloud upload branch later with `kvssink`

## Goals

- Keep the board fully headless. No GUI or local browser is assumed on the board.
- Keep `txing-board` as the only publisher of `board.*` state into the Thing Shadow.
- Let the web app discover the board video endpoint through the shared shadow.
- Require authentication before the browser can read the board WebRTC stream.
- Keep the media path compatible with a future second output branch for AWS upload.

## Non-Goals

- Cloud upload in phase 1
- Near-real-time cloud analysis in phase 1
- Multi-viewer access control in phase 1
- Audio in phase 1
- Browser-to-board control over a WebRTC data channel in phase 1

The original control-channel requirement is intentionally deferred. The phase 1 design focuses on an authenticated headless video path and leaves a clear extension point for later control transport work.

## Decision Summary

- `txing-board` remains the only AWS IoT Thing Shadow publisher for `board.*`.
- A new local media sidecar is introduced for video runtime state and authentication.
- Media serving is done by a dedicated headless network service, not by a GUI sample app.
- Phase 1 uses a bearer token surfaced through the shadow as the browser's read credential.
- The browser connects to a board-local WebRTC/WHEP endpoint over the board's IPv6 address.
- The camera capture pipeline is structured so a future `kvssink` branch can be added without redesigning the local path.

## High-Level Architecture

```text
Raspi Cam v3
  -> GStreamer publisher
  -> loopback publish to local MediaMTX path

MediaMTX
  -> serves WebRTC/WHEP to browser over network
  -> delegates stream auth to local HTTP auth endpoint

txing-board-media
  -> starts and supervises the GStreamer publisher
  -> owns the MediaMTX auth hook
  -> generates and rotates the local read token
  -> writes runtime state to /run/txing/board-media/state.json

txing-board
  -> reads /run/txing/board-media/state.json
  -> merges board video state with power / wifi state
  -> publishes reported.board.* to AWS IoT Thing Shadow

web
  -> reads board.wifi.ipv6 and board.video.local.* from shadow
  -> opens authenticated WebRTC/WHEP read session to the board
```

## Why This Shape

### Why not make the media service the shadow publisher

The current board process already owns `board.*`, and keeping a single publisher avoids sibling-subtree merge races, duplicate AWS credentials logic, and multi-process schema validation problems. The media sidecar should publish local runtime state only, while `txing-board` remains the single external source of truth.

### Why use a dedicated headless media server

Phase 1 needs a network-accessible service, not a local demo application or a GUI process. A dedicated media server gives:

- a stable long-running service model
- a concrete network endpoint the browser can call directly
- built-in WebRTC/WHEP serving
- built-in HTTP authentication hooks

### Why keep GStreamer in the design

GStreamer stays in the design as the camera ingest and publish path. The phase 1 serving layer is separated from the camera pipeline so the same encoded video can later fan out to additional outputs, including `kvssink`.

## Service Boundaries

### `txing-board`

Responsibilities:

- publish all `board.*` Thing Shadow updates
- continue handling `desired.board.power`
- read local media state from `/run/txing/board-media/state.json`
- include a `board.video` subtree in the reported shadow
- continue publishing board Wi-Fi status and IPv6 reachability metadata

Non-responsibilities:

- camera capture
- MediaMTX process supervision details
- browser stream authentication logic

### `txing-board-media`

Responsibilities:

- generate a read-only bearer token on startup
- rotate that token when the media service restarts
- supervise the local GStreamer publisher
- expose a local HTTP authentication endpoint for MediaMTX
- write current runtime state to `/run/txing/board-media/state.json`

Non-responsibilities:

- direct shadow publishing
- device power control

### MediaMTX

Responsibilities:

- expose the network-readable WebRTC/WHEP endpoint
- authenticate readers through a local HTTP callback
- serve the stream to the web app

Non-responsibilities:

- shadow integration
- AWS IoT integration
- token minting

## Authentication Model

Phase 1 uses a pragmatic local read token:

1. `txing-board-media` generates a random bearer token on startup.
2. The token is written to `/run/txing/board-media/state.json`.
3. `txing-board` publishes the token inside the `board.video.local.auth` shadow subtree.
4. The web app reads the token from shadow.
5. The web app sends the token in an `Authorization: Bearer <token>` header when opening the board-local WebRTC/WHEP read session.
6. MediaMTX calls the local auth endpoint.
7. The auth endpoint accepts only:
   - the current token
   - read access
   - the configured stream path
   - the WebRTC protocol

### Security Notes

- Anyone who can read the shadow can read the phase 1 token.
- Therefore shadow read access must remain limited to the intended admin identities.
- The token is single-purpose and read-only. It does not grant any board control operation.
- The token should rotate whenever the media service restarts.
- Future phases should replace the shadow-published token with a shorter-lived or per-session credential if broader access is needed.

## Proposed Shadow Shape

Phase 1 adds an optional `reported.board.video` subtree:

```json
{
  "state": {
    "reported": {
      "board": {
        "video": {
          "ready": true,
          "status": "ready",
          "local": {
            "protocol": "webrtc",
            "reader": "whep",
            "port": 8889,
            "path": "board-cam",
            "auth": {
              "token": "<opaque read token>",
              "issuedAt": "2026-03-20T12:00:00Z"
            }
          },
          "codec": {
            "video": "h264"
          },
          "viewerConnected": false
        }
      }
    }
  }
}
```

Notes:

- `board.wifi.ipv6` remains the source of the board address.
- The web app builds the stream URL from `board.wifi.ipv6`, `board.video.local.port`, and `board.video.local.path`.
- `status` is a small operational state, for example `starting`, `ready`, or `error`.
- A future phase can add `board.video.cloud.kvs.*` without changing the local reader contract.

## Runtime State File

`txing-board-media` writes a small JSON state file to:

- `/run/txing/board-media/state.json`

Minimum contents:

- media service status
- stream path
- listen port
- current read token
- token issuance time
- codec summary
- viewer connected flag
- last error, if any

This file is the only data source `txing-board` uses to mirror video state into the shadow.

## Browser Connection Flow

1. User signs into the existing web app.
2. Web reads the Thing Shadow.
3. Web checks:
   - `board.power`
   - `board.wifi.online`
   - `board.wifi.ipv6`
   - `board.video.ready`
4. Web builds the board-local WHEP URL from shadow metadata.
5. Web reads `board.video.local.auth.token`.
6. Web opens the board-local WebRTC/WHEP session with the bearer token.
7. MediaMTX validates the token through the local auth service.
8. Browser starts rendering the returned media stream.

Once phase 1 is live, the video session should not depend on repeated shadow polling.

## GStreamer Media Path

Phase 1 media production is intentionally simple:

- camera capture on the board
- low-latency H.264 encode
- local publish into MediaMTX over a loopback-friendly protocol

The internal publisher should still be built with a future fan-out in mind:

```text
camera source
  -> H.264 encode / parse
  -> output A: local MediaMTX publish
  -> output B: future kvssink branch
```

That future branch is out of scope for phase 1, but it is the main reason to keep the capture/encode path in a dedicated publisher service instead of tying it directly to the web-serving layer.

## Networking and TLS

Phase 1 assumes the browser reaches the board directly over the board's IPv6 address.

Requirements:

- the board must expose the WebRTC/WHEP HTTP endpoint on the network
- the web app must know the current board IPv6 address
- the board endpoint must be reachable from the admin browser
- the board endpoint needs a browser-acceptable TLS setup if the web app is served over HTTPS

The current board Wi-Fi reporting only resolves addresses at daemon start. That is insufficient for direct reader URLs and must be tightened before phase 1 is considered reliable.

## Operational Rules

- `txing-board` is the only shadow publisher for `board.*`.
- `txing-board-media` and MediaMTX are headless background services only.
- Phase 1 auth token is read-only and video-only.
- Power control stays on the shadow control path, not in the video auth token.

## Deferred Work

Not in phase 1:

- `kvssink`
- cloud upload
- browser-to-board control transport
- per-session token minting
- stricter multi-viewer policy
- audio

## External References

- MediaMTX authentication: https://mediamtx.org/docs/usage/authentication
- MediaMTX read a stream: https://mediamtx.org/docs/usage/read
- MediaMTX publish a stream: https://mediamtx.org/docs/usage/publish
- MediaMTX embed streams in a website: https://mediamtx.org/docs/usage/embed-streams-in-a-website
- Kinesis Video Streams GStreamer plugin: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/examples-gstreamer-plugin.html
