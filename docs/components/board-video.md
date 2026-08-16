# Shared Board Video

## Status

- Scope: current operator video over plain AWS WebRTC only
- Goal: one live operator path with minimal IT operations
- Current live-control target: `p95` operator glass-to-glass latency under `800 ms` on target links
- Control model: directional commands, not precision teleoperation
- Video viewing never grants control authority. Control, active-session, and
  REDCON rules remain in the owning device contract.
- Field-validation status: the current Unit video path is accepted as the
  behavior baseline; each device still requires its own physical acceptance.
- Current implementation: `txing-<device>-daemon` and the shared native
  `txing-board-kvs-master` are separately supervised. The daemon serves the
  local BoardVideoBridge gRPC socket, publishes retained video service topics,
  `rig` consumes them for REDCON readiness, and the browser uses AWS KVS
  signaling + WebRTC for the viewer path.

Explicit non-goals for this slice:

- HLS/DASH as the live control path
- WebRTC ingestion/storage as the default live path
- a separate multiviewer relay, media fanout service, or viewer admission-control service
- a second direct device-to-operator video path by default
- recording as a requirement
- low-latency ML consumption

## Current Design

- The board stays fully headless.
- `txing-<device>-daemon` publishes board power and wifi state for the stable
  Go runtime path.
- `txing-<device>-daemon` publishes retained video descriptor/status topics
  under `txings/<device_id>/video/*`.
- The current implementation uses one live video path only: board camera -> plain AWS WebRTC signaling channel -> one or more browser viewers.
- The operator watches the plain AWS WebRTC path, not a board-local viewer page.
- KVS dual-stack endpoints and IPv6-preferred TURN behavior are enabled by
  default for the current worker/browser path.
- The current implementation does not use WebRTC ingestion/storage, a separate
  multiviewer relay, or `kvssink`.
- The current implementation assumes one active human controller at a time, but
  does not enforce single-viewer admission control in the repo.
- ML and other cloud-side consumers are explicitly outside the current media path.
- A second direct operator path remains deferred. The recorded manual field validation did not justify reopening it.
- The native sender implementation is shipped in-tree as the
  `txing-board-kvs-master` release asset. Its OpenRC service supplies the
  device-specific worker identity and bridge sockets at runtime. The daemon and worker communicate
  through the language-neutral BoardVideoBridge gRPC contract.

## High-Level Architecture

```text
txing-<device>-daemon
  -> owns board power and wifi shadow state
  -> serves BoardVideoBridge gRPC over a Unix socket
  -> publishes retained board video descriptor/status topics
  -> tracks coarse board video readiness and failures

native sender command
  -> is shipped as txing-board-kvs-master
  -> owns the actual camera capture, encode, and single KVS master session
  -> creates one WebRTC peer session per viewer client on the same signaling channel
  -> connects to BoardVideoBridge for config, credentials, and video state

operator client
  -> connects as viewer through the KVS WebRTC signaling channel
  -> receives the live path negotiated by AWS signaling / ICE
  -> uses the device's separate control contract when it needs authority
```

## Retained MQTT Contract

The current implementation publishes retained board video service topics:

- `txings/<device_id>/video/descriptor` is a retained discovery/config record
  and has no MQTT message expiry.
- `txings/<device_id>/video/status` is retained dynamic state and is published
  with a MQTT 5 Message Expiry Interval equal to
  `TXING_CAPABILITY_TTL_SECONDS`, defaulting to `150` seconds. The daemon
  refreshes it at `TXING_HEARTBEAT_SECONDS`, defaulting to `60` seconds, so the
  retained liveness record remains inside that expiry window.

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

The retained video topics are used directly by `rig` for REDCON readiness and
by the owning device control contract for client-visible video runtime state.
The `video` named shadow is a durable read model, not a liveness heartbeat: the
daemon updates it at startup, shutdown, and video state transitions, but does
not rewrite it during an unchanged periodic heartbeat. The same rule applies
to the device-specific `mcp` or `mavlink` named shadow. Periodic heartbeats
refresh only retained dynamic status and capability topics.
Existing retained AWS IoT messages published before expiry was added are
replaced only by a same-topic daemon republish; orphaned retained topics require
manual AWS IoT retained-message cleanup if they matter operationally.

Notes:

- `transport=aws-webrtc` is the current choice.
- The canonical browser route path is `/<town>/<rig>/<device>/video`, computed by the SPA from the current device assignment.
- The AWS WebRTC signaling channel name is computed as `<device_id>-board-video`.
- The current implementation means plain KVS WebRTC signaling, not ingestion/storage.
- `board.video.local.*` is no longer part of the active contract.
- `ready` and `viewerConnected` are coarse runtime signals reported over the
  bridge, not a full media-quality guarantee.
- `viewerConnected` is a coarse observability boolean. It is not an
  admission-control signal and does not prove that only one viewer exists.

## Runtime Layout

### `txing-<device>-daemon`

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
- publish unavailable video state on daemon shutdown

The durable contract is documented in
[Board video bridge](../contracts/board-video-bridge.md).

### Native Sender Command

Responsibilities:

- provide the in-repo media-pipeline implementation
- open the board camera
- encode H.264
- establish the plain AWS WebRTC master session
- publish a single live path through one AWS KVS signaling channel
- maintain separate WebRTC peer sessions for viewer clients on that channel

### Operator Client

The operator client is the current client of this session model, not the only possible client type.

Responsibilities:

- join the plain AWS WebRTC viewer session
- render the live stream for directional control
- support the existing browser operator path

Operator scope note:

- one active human controller is the intended operational model
- multiple browser viewers may observe the same video channel at the same time
- video viewing does not grant control authority
- the current repo does not enforce single-viewer admission control

## Media Serving

The current implementation uses:

- plain AWS WebRTC signaling as the only live operator video path
- H.264 as the expected video codec
- one live uplink from the device
- one AWS KVS signaling channel per video-capable device
- one WebRTC peer session per connected viewer client on that channel
- no direct browser-to-board media path in the default design
- a repo-managed native sender that is supervised separately from the daemon

The current implementation does not use:

- WebRTC ingestion/storage
- a separate multiviewer relay or viewer admission-control service
- a repo-managed `kvssink`-based sender implementation
- HLS/DASH for live control
- a board-local iframe viewer page
- a second direct operator path by default

## Field Validation

Manual validation of the Unit path accepted the plain AWS WebRTC operator video
experience from a business perspective. That establishes the shared video
behavior baseline; it does not substitute for each device's physical-board
acceptance.

What is recorded for that acceptance:

- the Unit plain AWS WebRTC operator path was manually exercised in realistic
  use
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
- a separate multiviewer relay or viewer admission-control service
- HLS/DASH as the operator path
- a second direct operator video path unless future field use justifies it

## Future Enhancements

- A later implementation may add native iOS/Android operator clients using the same signaling/session model.
- A later implementation may add a separate cloud-consumption path for ML and other cloud-side consumers.
- Additional future clients may reuse the same session metadata and signaling model without changing the current browser-operator path.
- These future paths are outside the current operator media path and do not change the current AWS-WebRTC browser-operator design.
- Cloud/control-only session consumers are tracked in
  [Future work](../future-work.md).

## References

- AWS create signaling channel: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/create-channel.html
- AWS ConnectAsMaster: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/ConnectAsMaster.html
- AWS GetSignalingChannelEndpoint: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/API_GetSignalingChannelEndpoint.html
- AWS Kinesis Video Streams playback: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/how-playback.html
- AWS Kinesis Video Streams HLS playback: https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/hls-playback.html
- AWS Kinesis Video Streams WebRTC IPv6/Dual-Stack: https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/kvswebrtc-ipv6.html
