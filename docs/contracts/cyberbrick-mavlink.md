# Cyberbrick MAVLink capability contract

Cyberbrick has the `mavlink` capability and does not have `mcp`. Unit retains
its existing MCP capability and payloads. Catalog validation rejects a device
that declares both capabilities.

## Local ownership

`txing-cyberbrick-mavlink` is the only owner of the flight-controller
transport. It serves `txing.board.mavlink.v1.BoardMavlink` at
`unix:/run/txing-cyberbrick-mavlink/cyberbrick-mavlink.sock`.

- `GetStatus` reports link availability, heartbeat freshness, target system and
  component IDs, armed state, mode, MAVLink wire version, and structured
  errors.
- `Exchange` is a bidirectional exchange of complete, unsigned MAVLink 2
  common-dialect frames. It does not add RTC framing or rewrite any frame
  field.
- `EnterSafeState` requests neutral control and Hold, with optional ordinary
  disarm as a bounded best-effort action.

The board daemon is the sole authority for peer identity, active control,
takeover, epochs, lease expiry, REDCON, and cloud state. The KVS worker uses
`txing.board.mavlink_bridge.v1.BoardMavlinkBridge` only for control-channel
configuration and credentials, peer lifecycle, JSON controls, and binary frame
exchange. Opening a peer never grants authority.

The authoritative definitions are
[`mavlink.proto`](../../devices/cyberbrick/proto/txing/board/mavlink/v1/mavlink.proto)
and
[`mavlink_bridge.proto`](../../devices/cyberbrick/proto/txing/board/mavlink_bridge/v1/mavlink_bridge.proto).

## WebRTC data channel

MAVLink uses a data-only KVS/WebRTC peer connection independent of video. Its
single data channel is ordered and reliable with label `txing.mavlink.v1`.

- Each binary message is exactly one unsigned MAVLink 2 `common` frame.
  Invalid framing or CRC, signed frames, and unsupported messages are rejected.
- Text messages validate against
  [`mavlink-webrtc.schema.json`](../../devices/cyberbrick/protocol/mavlink-webrtc.schema.json).
  The only operations are `control.get_state`, `control.activate`,
  `control.renew_active`, and `control.release_active`.
- Successful state and mutation messages include an epoch and a five-second
  lease TTL. Errors are stable `control_busy`, `stale_epoch`, or
  `invalid_request` envelopes.

## Cloud and REDCON projection

The retained descriptor and status topics are
`txings/<thing>/mavlink/descriptor` and `txings/<thing>/mavlink/status`.
The descriptor has no expiry; status has the normal capability TTL. The MAVLink
named shadow contains link, target, armed/mode, peer, active-control, and error
state. It intentionally has no generic observation/update timestamp.

`resources.mavlink.channelName` renders as `<thing>-mavlink`. A healthy
MAVLink capability means the local service is healthy, the flight-controller
heartbeat is fresh, and the control KVS worker is ready; it does not require a
connected Office peer.

`mavlinkArmed` is an internal inventory metric rule for Cyberbrick REDCON1. It
is never published as a Sparkplug capability metric. A healthy, video-ready
Cyberbrick that becomes disarmed drops from REDCON1 to REDCON2.

Schemas and example payloads live in
[`devices/cyberbrick/aws`](../../devices/cyberbrick/aws/). The maintained topic
builders are in
[`shared/aws/python/src/aws/mavlink_topics.py`](../../shared/aws/python/src/aws/mavlink_topics.py).

## Cloud provisioning and forward-only rollout

Provision cloud state before any Cyberbrick board cutover:

1. Apply the shared AWS stack and current enlistment Lambda, then enlist or
   re-enlist the Cyberbrick with its existing rig and device name. Enlistment
   validates and creates both `<thing>-board-video` and `<thing>-mavlink`, and
   initializes missing capability shadows without replacing existing ones.
2. Generate a fresh Cyberbrick certificate bundle after that provisioning so
   its device credential role authorizes those two exact signaling channels.
   The Office role remains a KVS viewer; it is never granted `ConnectAsMaster`.
3. In a writable-root maintenance window, install the coordinated Cyberbrick
   board/runtime release, then reboot with the root read-only. Deploy Office
   only after the board cutover succeeds.
4. After the successful cutover, manually remove the obsolete Cyberbrick `mcp`
   named shadow and its retained descriptor/status messages.

There is no automatic cleanup, dual publication, compatibility shim, or
rollback to the former Cyberbrick MCP control path.

## Bindings

Pinned MAVLink 2 `common` C/C++ and TypeScript generated bindings, their
licenses, and regeneration verifier are in
[`devices/cyberbrick/mavlink`](../../devices/cyberbrick/mavlink/). Office uses
the checked-in definitions and local parser only; it has no runtime MAVLink npm
package.
