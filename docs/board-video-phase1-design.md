# Board Video MVP Design

## Status

- Scope: local MVP only
- Goal: show the board camera in the local Vite dev app over direct IPv6
- Explicit non-goals for this slice: auth, TLS, CloudFront compatibility, MediaMTX, cloud upload

## MVP Decisions

- The board stays fully headless.
- `txing-board` remains the only publisher of `board.*` state into the shared Thing Shadow.
- A separate `txing-board-media` service supervises the local GStreamer rswebrtc publisher.
- The media stack is GStreamer-only for the MVP:
  - producer on the board: `webrtcsink`
  - browser client on the Mac: `gstwebrtc-api`
- The browser connects directly to the board over IPv6 through the rswebrtc signaling server.
- The MVP is single-viewer and local-dev only.

## High-Level Architecture

```text
Raspi Cam v3 or overrideable source pipeline
  -> GStreamer H.264 source fragment
  -> webrtcsink
  -> built-in rswebrtc signaling server

txing-board-media
  -> supervises the gst-launch pipeline
  -> writes /run/txing/board-media/state.json

txing-board
  -> reads /run/txing/board-media/state.json
  -> merges board.video.* into reported.board.*
  -> publishes the combined board state to AWS IoT

web (local Vite dev on the Mac)
  -> reads board.video.local.signallingUrl and streamName from shadow
  -> connects directly to the board with gstwebrtc-api
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
            "signallingUrl": "ws://[2001:db8::25]:8443",
            "streamName": "board-cam"
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

- `signallingUrl` is the direct rswebrtc WebSocket signaling URL for the browser.
- `streamName` is the fixed producer name advertised through `webrtcsink`.
- `viewerConnected` remains conservative in the MVP because the media service supervises `gst-launch-1.0` as a subprocess.

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

- launch and restart the board-local GStreamer rswebrtc pipeline
- publish runtime state to `/run/txing/board-media/state.json`
- set the stream name to `board-cam`
- publish the direct signaling URL derived from the current board IPv6 address and signaling port

### Browser

Responsibilities:

- run from the local Vite dev server
- consume `board.video.local.signallingUrl` and `board.video.local.streamName`
- connect directly to the board using `gstwebrtc-api`

## Media Serving

The MVP uses:

- `webrtcsink`
- `run-signalling-server=true`
- `run-web-server=false`
- `enable-control-data-channel=false`
- stream metadata name `board-cam`
- signaling port `8443`
- host ICE only for the MVP

The Python service supervises `gst-launch-1.0` instead of embedding GStreamer bindings. That keeps the MVP simpler and avoids taking a dependency on `gi` / `PyGObject` inside the project runtime.

## Deferred

Not part of the MVP:

- auth
- TLS
- MediaMTX
- WHEP
- deployed HTTPS SPA compatibility
- browser-to-board control transport
- `kvssink`
- cloud upload

## References

- rswebrtc: https://gstreamer.freedesktop.org/documentation/rswebrtc/index.html
- webrtcsink: https://gstreamer.freedesktop.org/documentation/rswebrtc/webrtcsink.html
- gstwebrtc-api: https://gitlab.freedesktop.org/gstreamer/gst-plugins-rs/-/tree/main/net/webrtc/gstwebrtc-api
