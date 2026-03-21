# Board Video Phase 1 Design

## Status

- Scope: local MVP only
- Goal: show the board camera in the local Vite dev app over direct IPv6
- Explicit non-goals for this slice: auth, TLS, CloudFront compatibility, browser-to-board control transport, cloud upload

## MVP Decisions

- The board stays fully headless.
- `txing-board` remains the only publisher of `board.*` state into the shared Thing Shadow.
- A separate `txing-board-media` service supervises the local GStreamer publisher.
- MediaMTX is used as a separate operator-installed service:
  - publisher on the board: `gst-launch-1.0` with `rtspclientsink`
  - browser path on the Mac: MediaMTX built-in WebRTC viewer page loaded in an `iframe`
- The browser connects directly to the board over IPv6 through the MediaMTX viewer URL.
- The MVP is single-viewer and local-dev only.

## High-Level Architecture

```text
Raspi Cam v3 or overrideable source pipeline
  -> GStreamer H.264 source fragment
  -> rtph264pay
  -> rtspclientsink
  -> rtsp://127.0.0.1:8554/board-cam

MediaMTX
  -> ingests RTSP publisher on board-cam
  -> serves WebRTC viewer page on http://[board-ipv6]:8889/board-cam

txing-board-media
  -> supervises the gst-launch publisher pipeline
  -> writes /run/txing/board-media/state.json

txing-board
  -> reads /run/txing/board-media/state.json
  -> merges board.video.* into reported.board.*
  -> publishes the combined board state to AWS IoT

web (local Vite dev on the Mac)
  -> reads board.video.local.viewerUrl from shadow
  -> loads that URL in an iframe
```

## Shadow Contract

The MVP adds `reported.board.video`:

```json
{
  "state": {
    "reported": {
      "board": {
        "video": {
          "ready": true,
          "status": "ready",
          "local": {
            "viewerUrl": "http://[2001:db8::25]:8889/board-cam",
            "streamPath": "board-cam"
          },
          "codec": {
            "video": "h264"
          },
          "viewerConnected": false,
          "lastError": null
        }
      }
    }
  }
}
```

Notes:

- `viewerUrl` is the exact MediaMTX page the local Vite app should load in an iframe.
- `streamPath` is the fixed MediaMTX path published by `txing-board-media`.
- `viewerConnected` remains conservative in the MVP because MediaMTX owns the browser sessions, not the Python service.

## Runtime Split

### `txing-board`

Responsibilities:

- publish all `board.*` Thing Shadow updates
- keep handling `desired.board.power`
- refresh board IPv4 and IPv6 on each publish loop
- read `/run/txing/board-media/state.json`
- mirror `board.video.*` into the reported shadow

### `txing-board-media`

Responsibilities:

- launch and restart the board-local GStreamer publisher pipeline
- publish runtime state to `/run/txing/board-media/state.json`
- set the stream path to `board-cam`
- publish the exact viewer URL derived from the current board IPv6 address and MediaMTX viewer port

### MediaMTX

Responsibilities:

- accept RTSP publish on `rtsp://127.0.0.1:8554/board-cam`
- serve the WebRTC viewer page on `http://[board-ipv6]:8889/board-cam`
- remain a separate operator-installed service outside of AWS IoT publishing

### Browser

Responsibilities:

- run from the local Vite dev server
- consume `board.video.local.viewerUrl`
- load the MediaMTX viewer page in an iframe

## Media Serving

The MVP uses:

- `libcamerasrc`
- `v4l2h264enc`
- `h264parse`
- `rtph264pay`
- `rtspclientsink`
- MediaMTX RTSP ingest on `127.0.0.1:8554`
- MediaMTX WebRTC viewer page on port `8889`

The Python service supervises `gst-launch-1.0` instead of embedding GStreamer bindings. That keeps the MVP simple and avoids taking a dependency on `gi` / `PyGObject` inside the project runtime.

## Deferred

Not part of the MVP:

- auth
- TLS
- deployed HTTPS SPA compatibility
- browser-to-board control transport
- `kvssink`
- cloud upload

## References

- MediaMTX overview: https://mediamtx.org/
- MediaMTX embed streams: https://mediamtx.org/docs/other/embed-streams-in-a-website
- MediaMTX configuration reference: https://mediamtx.org/docs/references/configuration-file
