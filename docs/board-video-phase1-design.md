# Board Video Phase 1 Design

## Status

- Scope: v1 operator video over plain AWS WebRTC only
- Goal: one live operator path with minimal IT operations
- Live-control target: `p95` operator glass-to-glass latency under `800 ms` on target links
- Control model: directional commands, not precision teleoperation
- Field-test rule: this phase-1 choice can be changed after field tests if the plain-AWS-WebRTC path does not deliver acceptable operator quality
- Current repo implementation: `txing-board` publishes `board.video.*`, supervises a dedicated sender state manager, and the browser uses AWS KVS signaling + WebRTC for the viewer path

Explicit non-goals for this slice:

- HLS/DASH as the live control path
- WebRTC ingestion/storage as the default phase-1 path
- multiviewer as a requirement
- a second direct device-to-operator video path by default
- recording as a requirement
- low-latency ML consumption

## Phase 1 Decision

- The board stays fully headless.
- `txing-board` remains the only publisher of `board.*` state into the shared Thing Shadow.
- Phase 1 uses one live video path only: board camera -> plain AWS WebRTC signaling channel -> operator.
- The operator watches the plain AWS WebRTC path, not a board-local viewer page.
- Phase 1 does not use WebRTC ingestion/storage, multiviewer, or `kvssink`.
- ML and other cloud-side consumers are explicitly outside the phase-1 media path. If they need video later, that will require a separate follow-on design.
- A second direct operator path remains a fallback option only if field tests show the plain-AWS-WebRTC path is not good enough.
- In the current repo, the actual native sender command is injected at runtime and supervised by `board.video_sender`; the repo does not embed the media-pipeline implementation directly.

## High-Level Architecture

```text
txing-board
  -> owns board.* shadow state
  -> supervises board video sender state
  -> reports board.video transport/session metadata
  -> tracks coarse board video readiness and failures

board video sender state manager
  -> validates the KVS signaling channel exists
  -> launches the externally configured native sender command
  -> marks sender ready from child output or fallback startup timeout
  -> tracks best-effort viewer connected/disconnected state from child output markers

native sender command
  -> owns the actual camera capture, encode, and KVS master session

operator client
  -> connects as viewer through the KVS WebRTC signaling channel
  -> receives the live path negotiated by AWS signaling / ICE
  -> sends directional commands out of band as strict ROS `geometry_msgs/Twist`
```

## Shadow Contract

Phase 1 uses `reported.board.video` to describe the plain AWS WebRTC live path:

```json
{
  "state": {
    "reported": {
      "board": {
        "video": {
          "ready": true,
          "status": "ready",
          "transport": "aws-webrtc",
          "session": {
            "viewerUrl": "https://ops.example.com/txing/video",
            "channelName": "txing-board-video"
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

- `transport=aws-webrtc` is the phase-1 choice.
- `session.viewerUrl` is the browser entry point when a browser operator route exists.
- `session.channelName` is the AWS WebRTC signaling channel name for browser or native clients.
- Phase 1 means plain KVS WebRTC signaling, not ingestion/storage.
- `board.video.local.*` is no longer part of the active phase-1 contract.
- `ready` and `viewerConnected` are coarse runtime signals derived from the supervised sender state, not a full media-quality guarantee.

## Runtime Layout

### `txing-board`

Responsibilities:

- publish all `board.*` Thing Shadow updates
- keep handling internal `desired.board.power`
- refresh board IPv4 and IPv6 on each publish loop
- publish board video transport/session metadata
- supervise the local board video sender state manager
- gate `board.video.ready` on sender readiness rather than any board-local iframe endpoint
- surface the last coarse media error through `board.video.lastError`

### Board Video Sender State Manager

Responsibilities:

- validate the configured signaling channel before steady-state sender supervision
- run the actual native sender command provided at runtime
- persist local sender state for `txing-board`
- translate sender output markers into coarse `ready` / `viewerConnected` state
- keep the repo-managed path simple enough for field validation in v1

### Native Sender Command

Responsibilities:

- open the board camera
- encode H.264
- establish the plain AWS WebRTC master session
- publish a single live path to the operator

### Operator Client

Responsibilities:

- join the plain AWS WebRTC viewer session
- render the live stream for directional control
- translate browser key presses into strict ROS `Twist` commands for `txing/board/cmd_vel`
- support the existing browser operator first; future native-client support remains a design goal, not a completed implementation

Control contract notes:

- `txing/board/cmd_vel` uses strict ROS `Twist` semantics, not browser-specific steering semantics.
- `linear.x` is forward velocity in `m/s` and `angular.z` is yaw rate in `rad/s`.
- Browser teleop step sizes are a UI policy only. The shared MQTT contract for browser and AI producers remains the strict `Twist` meaning above.
- Board runtime track status reported in Thing Shadow is a separate provisional contract: `reported.board.drive.leftSpeed` and `rightSpeed` are signed percent values in `[-100, 100]` for this phase.

## Media Serving

Phase 1 uses:

- plain AWS WebRTC signaling as the only live operator video path
- H.264 as the expected video codec
- one live uplink from the device
- no direct browser-to-board media path in the default design
- a repo-managed sender supervisor that launches an externally configured native sender command

Phase 1 does not use:

- WebRTC ingestion/storage
- multiviewer
- a repo-managed `kvssink`-based sender implementation
- HLS/DASH for live control
- a board-local iframe viewer page
- a second direct operator path by default

## Field Tests

Field tests decide whether phase 1 stays AWS-WebRTC-only or reopens a second direct operator path.

Measure at minimum:

- `p95` operator glass-to-glass latency against the `800 ms` target
- operator control quality for directional commands
- jitter and short-stall behavior under weaker links
- reconnect behavior after temporary link loss

Revisit the architecture if:

- `p95` latency misses the target
- operator control quality is poor even when average latency looks acceptable
- the plain AWS WebRTC path adds too much variability for practical use

## Deferred

Not part of phase 1:

- recording as a requirement
- low-latency ML consumption
- cloud-side video ingestion/storage
- multiviewer
- HLS/DASH as the operator path
- a second direct operator video path unless field tests justify it

## References

- AWS create signaling channel: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/create-channel.html
- AWS ConnectAsMaster: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/ConnectAsMaster.html
- AWS GetSignalingChannelEndpoint: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/API_GetSignalingChannelEndpoint.html
- AWS Kinesis Video Streams playback: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/how-playback.html
- AWS Kinesis Video Streams HLS playback: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/hls-playback.html
- AWS Kinesis Video Streams WebRTC IPv6/Dual-Stack: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/kvswebrtc-ipv6.html
