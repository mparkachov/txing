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
with label `txing.mavlink.v1`. Each binary message is exactly one complete
MAVLink 2 frame, signed or unsigned. The board preserves those binary frames
byte-for-byte: it does not select a dialect, validate a dialect-specific CRC,
rewrite source or target IDs, or filter MAVLink message types. The flight
controller is the protocol authority and validates the tunneled frames.

An observer peer is receive-only. After it acquires the active-control lease,
the peer has a full bidirectional MAVLink tunnel; the lease is the only board
write gate. The small JSON control envelopes are solely the authority and
lease protocol, not a replacement for MAVLink. They remain defined in
[`mavlink-webrtc.schema.json`](../../devices/common/board/protocol/mavlink-webrtc.schema.json).

## Office operation and safety semantics

Office presents two operator modes for every MAVLink-capable board:

- **View only** is the default. A connected peer can observe telemetry but
  cannot transmit control frames.
- **Control** starts only after the operator acquires the active-control lease.
  The Office client prepares the flight controller for manual driving, then
  sends `MANUAL_CONTROL` at 10 Hz, including neutral frames while no arrow key
  is held. Arm state and Manual/Hold selection are flight-controller details,
  not separate Office control modes.

This Office behavior is a client policy only. It limits what Office sends but
does not constrain other active MAVLink clients using the same data channel.
Such a client may use the full MAVLink 2 protocol and any dialect supported by
the attached flight controller.

The five-second active-control lease remains the authority boundary. Releasing
control, closing the active peer, or lease expiry immediately requests neutral,
Hold, and ordinary disarm. A 500 ms gap in accepted `MANUAL_CONTROL` frames is
only a drive-input watchdog: it requests neutral without releasing the lease,
changing mode, or disarming. This makes an idle control session equivalent to
released keys while preserving the established observer/control model.

`txing.mavlink.v1`, the one-frame-per-binary-message representation, JSON
operation names, error codes, and the descriptor's legacy
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

The bindings support the Office manual-driving client; they are not a tunnel
allowlist. A device's runtime service naming, flight-controller transport, and
hardware ownership remain in that device's implementation and release work.
