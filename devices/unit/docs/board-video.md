# Board Video

## Status

- Scope: current operator video over plain AWS WebRTC only
- Goal: one live operator path with minimal IT operations
- Current live-control target: `p95` operator glass-to-glass latency under `800 ms` on target links
- Control model: directional commands, not precision teleoperation
- Active-control model: one MCP session owns actuator authority; explicit
  `control.activate` with `takeover: true` switches ownership
- Field-validation status: manual field validation was completed and accepted the plain-AWS-WebRTC path from a business perspective; no lab-grade metrics dataset is recorded in-repo
- Current implementation: `txing-unit-daemon` and the native
  `txing-board-kvs-master` run as separate systemd services. The daemon serves
  the local BoardVideoBridge gRPC socket, publishes retained video service
  topics, `rig` consumes them for REDCON readiness, and the browser uses AWS
  KVS signaling + WebRTC for the viewer path. When video is ready, MCP control
  uses the `txing.mcp.v1` data channel on the same media peer connection; MQTT
  MCP is the REDCON `2` fallback when video is unavailable/not ready.

Explicit non-goals for this slice:

- HLS/DASH as the live control path
- WebRTC ingestion/storage as the default live path
- multiviewer as a requirement
- a second direct device-to-operator video path by default
- recording as a requirement
- low-latency ML consumption

## Current Design

- The board stays fully headless.
- `txing-unit-daemon` publishes board power and wifi state for the stable Rust
  runtime path.
- `txing-unit-daemon` publishes retained video descriptor/status topics under `txings/<device_id>/video/*`.
- The current implementation uses one live video path only: board camera -> plain AWS WebRTC signaling channel -> operator.
- The operator watches the plain AWS WebRTC path, not a board-local viewer page.
- KVS dual-stack endpoints and IPv6-preferred TURN behavior are enabled by
  default for the current worker/browser path.
- The current implementation does not use WebRTC ingestion/storage, multiviewer, or `kvssink`.
- The current implementation assumes one human operator at a time operationally, but does not enforce single-viewer admission control in the repo.
- ML and other cloud-side consumers are explicitly outside the current media path.
- A second direct operator path remains deferred. The recorded manual field validation did not justify reopening it.
- The native sender implementation is shipped in-tree and packaged as the
  `txing-board-kvs-master` release asset. The daemon and worker communicate
  through the language-neutral BoardVideoBridge gRPC contract.

## High-Level Architecture

```text
txing-unit-daemon
  -> owns board power and wifi shadow state
  -> serves BoardVideoBridge gRPC over a Unix socket
  -> publishes retained board video descriptor/status topics
  -> tracks coarse board video readiness and failures

native sender command
  -> is shipped as txing-board-kvs-master
  -> owns the actual camera capture, encode, and KVS master session
  -> connects to BoardVideoBridge for config, credentials, state, and MCP forwarding

operator client
  -> connects as viewer through the KVS WebRTC signaling channel
  -> receives the live path negotiated by AWS signaling / ICE
  -> sends directional commands through board MCP using strict ROS `geometry_msgs/Twist`
     over the media WebRTC data channel at REDCON 1, or MQTT MCP at REDCON 2
```

## Retained MQTT Contract

The current implementation publishes retained board video service topics:

```json
// txings/<device_id>/video/descriptor
{
  "serviceId": "video",
  "serverInfo": {
    "name": "video",
    "version": "<daemon-version>"
  },
  "topicRoot": "txings/<device_id>/video",
  "descriptorTopic": "txings/<device_id>/video/descriptor",
  "statusTopic": "txings/<device_id>/video/status",
  "transport": "aws-webrtc",
  "channelName": "<device_id>-board-video",
  "region": "<aws-region>",
  "serverVersion": "<daemon-version>"
}
```

```json
// txings/<device_id>/video/status
{
  "serviceId": "video",
  "available": true,
  "ready": true,
  "status": "ready",
  "viewerConnected": false,
  "lastError": null,
  "updatedAtMs": 1776761234567
}
```

The retained video topics are used directly by `rig` for REDCON readiness and by board MCP `robot.get_state` for client-visible video runtime state.

Notes:

- `transport=aws-webrtc` is the current choice.
- The canonical browser route path is `/<town>/<rig>/<device>/video`, computed by the SPA from the current device assignment.
- The AWS WebRTC signaling channel name is computed as `<device_id>-board-video`.
- The current implementation means plain KVS WebRTC signaling, not ingestion/storage.
- `board.video.local.*` is no longer part of the active contract.
- `ready` and `viewerConnected` are coarse runtime signals reported over the
  bridge, not a full media-quality guarantee.
- Single-operator scope is an operational assumption only. `viewerConnected` is not an admission-control signal and does not prove that only one viewer exists.

## Runtime Layout

### `txing-unit-daemon`

Responsibilities:

- publish board power and wifi Thing Shadow updates
- halt locally when Sparkplug `DCMD.redcon=4` arrives for the assigned device
- refresh board IPv4 and IPv6 on each publish loop
- serve the BoardVideoBridge gRPC socket for the native KVS master
- publish retained video descriptor/status topics
- gate retained video `ready` on sender readiness rather than any board-local iframe endpoint
- surface the last coarse media error through retained video `lastError`

### BoardVideoBridge

Responsibilities:

- provide worker config and IoT role-alias temporary credentials
- refresh credentials before expiry without requiring a process restart
- receive coarse `STARTING`, `READY`, `ERROR`, and viewer-count state
- forward opaque MCP JSON-RPC bytes by explicit `mcp_session_id`
- keep active-control policy, takeover, epochs, and REDCON in the daemon
- publish unavailable video state on daemon shutdown

The durable contract is documented in
[docs/contracts/board-video-bridge.md](../../../docs/contracts/board-video-bridge.md).

### Native Sender Command

Responsibilities:

- provide the in-repo media-pipeline implementation
- open the board camera
- encode H.264
- establish the plain AWS WebRTC master session
- publish a single live path to the operator

### Operator Client

The operator client is the current client of this session model, not the only possible client type.

Responsibilities:

- join the plain AWS WebRTC viewer session
- render the live stream for directional control
- translate browser key presses into strict ROS `Twist` commands for MCP `cmd_vel.publish`
- support the existing browser operator path

Operator scope note:

- one human operator is the intended operational model
- the current repo does not enforce single-viewer admission control

Control contract notes:

- MCP `cmd_vel.publish` uses strict ROS `Twist` semantics, not browser-specific steering semantics.
- `linear.x` is forward velocity in `m/s` and `angular.z` is yaw rate in `rad/s`.
- Browser teleop step sizes are a UI policy only. The shared MQTT contract for browser and AI producers remains the strict `Twist` meaning above.
- Current motion feedback is read through board MCP `robot.get_state`, not through Thing Shadow.

## Media Serving

The current implementation uses:

- plain AWS WebRTC signaling as the only live operator video path
- H.264 as the expected video codec
- one live uplink from the device
- no direct browser-to-board media path in the default design
- a repo-managed native sender that runs as its own systemd service by default

The current implementation does not use:

- WebRTC ingestion/storage
- multiviewer
- a repo-managed `kvssink`-based sender implementation
- HLS/DASH for live control
- a board-local iframe viewer page
- a second direct operator path by default

## Field Validation

The current implementation has already been accepted through manual field validation from a business perspective.

What is recorded for that acceptance:

- the plain AWS WebRTC operator path was manually exercised in realistic use
- practical directional-control quality was considered good enough for business use
- no second direct operator path was justified by that manual validation

What is not recorded for that acceptance:

- no lab-grade `p95` glass-to-glass latency dataset against the `800 ms` target
- no formal jitter or short-stall benchmark dataset
- no formal reconnect benchmark report

Future architecture work should reopen only if later field use shows that operator quality is no longer acceptable in practice.

## Deferred

Not part of the current implementation:

- recording as a requirement
- low-latency ML consumption
- cloud-side video ingestion/storage
- multiviewer
- HLS/DASH as the operator path
- a second direct operator video path unless future field use justifies it

## Future Enhancements

- A later implementation may add native iOS/Android operator clients using the same signaling/session model.
- A later implementation may add a separate cloud-consumption path for ML and other cloud-side consumers.
- Additional future clients may reuse the same session metadata and signaling model without changing the current browser-operator path.
- These future paths are outside the current operator media path and do not change the current AWS-WebRTC browser-operator design.
- Cloud/control-only session consumers are tracked in
  [docs/future-work.md](../../../docs/future-work.md).

## References

- AWS create signaling channel: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/create-channel.html
- AWS ConnectAsMaster: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/ConnectAsMaster.html
- AWS GetSignalingChannelEndpoint: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/API_GetSignalingChannelEndpoint.html
- AWS Kinesis Video Streams playback: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/how-playback.html
- AWS Kinesis Video Streams HLS playback: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/hls-playback.html
- AWS Kinesis Video Streams WebRTC IPv6/Dual-Stack: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/kvswebrtc-ipv6.html
