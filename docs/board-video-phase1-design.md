# Board Video Phase 1 Design

## Status

- Scope: local MVP only
- Goal: show the board camera in the local Vite dev app over the local LAN
- Explicit non-goals for this slice: auth, TLS, CloudFront compatibility, browser-to-board control transport, cloud upload

## MVP Decisions

- The board stays fully headless.
- `txing-board` remains the only publisher of `board.*` state into the shared Thing Shadow.
- MediaMTX is the camera owner and browser-ready WebRTC server:
  - camera source on the board: MediaMTX `rpiCamera`
  - browser path on the Mac: MediaMTX built-in viewer page loaded in an `iframe`
- A separate `txing-board-media` service only monitors MediaMTX and writes runtime state.
- The published viewer URL prefers the board's default-route IPv4 address and falls back to IPv6 if IPv4 is unavailable.
- The MVP is single-viewer and local-dev only.

## High-Level Architecture

```text
Raspi Cam v3
  -> MediaMTX rpiCamera source
  -> WebRTC viewer page on http://<board-ipv4>:8889/board-cam/

txing-board-media
  -> probes MediaMTX locally
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
            "viewerUrl": "http://192.168.0.10:8889/board-cam/",
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
- `streamPath` is the fixed MediaMTX path.
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

- probe the local MediaMTX viewer page
- publish runtime state to `/run/txing/board-media/state.json`
- set the stream path to `board-cam`
- publish the exact viewer URL derived from the current board address and MediaMTX viewer port

### MediaMTX

Responsibilities:

- open the Raspberry Pi camera directly with `source: rpiCamera`
- encode `1920x1080` at `30 fps` with hardware H.264
- serve the WebRTC viewer page on port `8889`
- remain a separate operator-installed service outside of AWS IoT publishing

### Browser

Responsibilities:

- run from the local Vite dev server
- consume `board.video.local.viewerUrl`
- load the MediaMTX viewer page in an iframe

## Media Serving

The MVP uses:

- MediaMTX `rpiCamera`
- `rpiCameraWidth: 1920`
- `rpiCameraHeight: 1080`
- `rpiCameraFPS: 30`
- `rpiCameraCodec: hardwareH264`
- MediaMTX WebRTC viewer page on port `8889`

The Python service does not own the media pipeline. It only reports local MediaMTX readiness and publishes the browser URL into the Thing Shadow.

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
- MediaMTX publish a stream: https://mediamtx.org/docs/usage/publish
- MediaMTX embed streams: https://mediamtx.org/docs/other/embed-streams-in-a-website
- MediaMTX configuration reference: https://mediamtx.org/docs/references/configuration-file
