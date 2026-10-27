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

The worker serializes complete SDK data-channel sends for each MAVLink peer.
Binary telemetry and text control replies originate on different threads; the
pinned SDK shares mutable SCTP send metadata between calls. Closing a peer
blocks later channel binding, waits for in-flight sends, then joins the local
telemetry reader before freeing the SDK peer. Late callbacks cannot write to a
closed or replaced channel. This preserves the message type and bytes without
changing the control envelopes or lease rules.

An observer peer is receive-only. After it acquires the active-control lease,
the peer has a full bidirectional MAVLink tunnel; the lease is the only board
write gate. The small JSON control envelopes are solely the authority and
lease protocol, not a replacement for MAVLink. They remain defined in
[`mavlink-webrtc.schema.json`](../../devices/common/board/protocol/mavlink-webrtc.schema.json).

Control RPCs and uplink frame exchange are independent local gRPC calls. A
queued frame may reach authorization after release, lease expiry, or takeover.
The daemon drops frames carrying an inactive or stale epoch without closing
the observer stream or deleting the peer. The same connected peer can acquire
control again explicitly; stale frames remain blocked after that acquisition.

The native worker initializes the WebRTC SDK once for its process lifetime.
Video and MAVLink keep independent signaling sessions, but share the SDK's
SRTP, SCTP, and thread-pool runtime. Replacing or stopping one session must not
deinitialize the runtime used by the other. Startup failures stop and join the
control thread before the worker exits.

On a camera or video failure, the worker stops the video session to drain its
viewer-count READY callbacks, then publishes video ERROR before releasing the
camera. Camera cleanup can wait on removed hardware and must not delay video
unavailability or peer closure. The independent MAVLink loop remains available
until the worker is stopped; restoring video requires a supervised restart
with a functioning camera. Failure-stage markers distinguish video closure,
camera release entry and camera release completion without exposing media or
credentials.

The worker emits `TXING_MAVLINK_DIAGNOSTICS` from its existing cleanup loop at
most once per five seconds per peer, and at teardown entry (`final=1`). Fixed
operation groups cover receive callbacks, control bridge dispatch, uplink
bridge writes, telemetry/reply sends including writer-lock waits, and actual
SDK sends. Each group reports started/finished/failed counts, pending count and
age, and last/maximum elapsed time. An SDK status code, wall-clock timestamp,
steady-clock timestamp and local numeric peer instance complete the record.
No frame/JSON content, credentials, SDP, TURN data or remote identity enters
this diagnostic line.

Counter reads do not acquire callback, send or bridge locks. Samples are
approximate across fields, and pending age uses the most recent operation
start if multiple calls overlap. Teardown entry is not proof that cleanup
finished. Blocking cleanup, signaling maintenance or output can delay later
samples; a sampling gap alone does not identify a particular lock. Diagnostics
do not change authority, retry, queues, deadlines or transport behavior.

## Office operation and safety semantics

Office presents two operator modes for every MAVLink-capable board:

- **View only** is the default. A connected peer can observe telemetry but
  cannot transmit control frames.
- **Control** starts only after the operator acquires the active-control lease.
  The explicit Office action requests `takeover=true` regardless of cached
  owner information, so a human can displace another controller without first
  refreshing the page.
  The Office client prepares the flight controller for manual driving, then
  sends `MANUAL_CONTROL` at 10 Hz, including neutral frames while no arrow key
  is held. Arm state and Manual/Hold selection are flight-controller details,
  not separate Office control modes.

Office starts its observer peer only when the Sparkplug projection reports
`capability.mavlink=true`. A negotiation that does not open the data channel
within 20 seconds closes its peer and signaling resources and uses the existing
reconnect backoff (1 second, doubling up to 10 seconds). Capability loss or route
changes cancel pending negotiations and close established peers. A reconnect
returns to View only; acquiring or taking over control remains an explicit
operator action.

An established Office peer with no received messages for fifteen seconds is
closed and replaced through that existing recovery path. A control-request
timeout also closes the session instead of letting later button clicks reuse
the same unresponsive channel. Late messages from the retired session cannot
restore authority or update its flight state. Failed acquisition is never
automatically replayed; the next takeover requires another explicit action on
the recovered connection. Ordinary Manual/Arm preparation and release after
preparation failure retain their existing semantics.

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
