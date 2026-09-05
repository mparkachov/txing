# Board MAVLink capability contract

The board MAVLink control protocol is shared by every board device type that
declares the `mavlink` capability. It is intentionally separate from the
device-owned MAVLink service and flight-controller configuration.

## Shared local and WebRTC interfaces

The board daemon owns peer identity, active-control authority, lease epochs,
takeovers, REDCON, and cloud state. A local MAVLink service owns only the
flight-controller transport. The KVS worker uses the daemon bridge for
control-channel configuration and peer lifecycle; opening a peer does not grant
control.

The authoritative local API definitions are:

- [`mavlink.proto`](../../devices/common/board/proto/txing/board/mavlink/v1/mavlink.proto)
  for `txing.board.mavlink.v1.BoardMavlink`.
- [`mavlink_bridge.proto`](../../devices/common/board/proto/txing/board/mavlink_bridge/v1/mavlink_bridge.proto)
  for `txing.board.mavlink_bridge.v1.BoardMavlinkBridge`.

MAVLink uses an independent ordered, reliable KVS/WebRTC data-only connection
with label `txing.mavlink.v1`. Each binary message is one complete unsigned
MAVLink 2 `common` frame. Text messages are the stable request, response, and
error envelopes in
[`mavlink-webrtc.schema.json`](../../devices/common/board/protocol/mavlink-webrtc.schema.json).

`txing.mavlink.v1`, the complete binary frame representation, JSON operation
names, error codes, and the descriptor's legacy
`cyberbrick-mavlink-control-json-v1` text-message value are wire values. They
must not change when another board device adopts the capability.

## Device-owned profile

Each device type owns its own MAVLink descriptor/status schemas, `mavlink`
named-shadow schema and default, fixtures, and manifest entry. A MAVLink device
must declare `resources.mavlink.channelName = "{device_id}-mavlink"` and must
not declare `mcp`; catalog validation rejects declaring both.

MAVLink arm state is independent flight-safety state. It remains visible in the
device's MAVLink status, but it neither gates REDCON nor changes board-video
availability. REDCON 1 reflects ready MAVLink and video capabilities.

The pinned MAVLink 2 `common` C/C++ and TypeScript generated bindings, their
license, golden vector, and regeneration verifier are shared at
[`devices/common/board/mavlink`](../../devices/common/board/mavlink/). Run:

```sh
just common::board::mavlink::test-bindings
just common::board::mavlink::regeneration-check
```

This contract defines shared protocol ownership only. A device's runtime
service naming, flight-controller transport, and hardware ownership remain in
that device's implementation and release work.
