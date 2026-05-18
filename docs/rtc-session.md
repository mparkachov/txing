# RTC Session Architecture

## Status

This document records the architecture direction for moving unit board control
from the current Python board runtime into the Rust unit daemon while preserving
the existing browser operator behavior.

This is a migration plan. Phase 2a is the current implementation target:
restore KVS video under the Rust daemon while keeping MCP MQTT-only. Phase 2b
and later sections remain forward design.

## Intention

The unit daemon should become the owner of board-side control behavior:

- board capability publication
- motor control and software watchdogs
- MCP server state, sessions, tools, and active control authority
- MQTT MCP fallback transport
- supervision of the native RTC/KVS worker
- publication of retained MCP and video descriptor/status topics

The native KVS/WebRTC implementation should remain a separate local worker. In
Phase 2a it owns AWS KVS WebRTC master behavior, camera capture, and H.264
media only. WebRTC data-channel bridging is deferred to Phase 2b. The worker is
a media/RTC endpoint provider, not the owner of MCP business logic or motor
authority.

The architecture should make video an optional media capability of an RTC
session. MCP over WebRTC is a control transport that can ride on the same RTC
session when video is available. This keeps video and MCP separated at the
application boundary while allowing the implementation to share the AWS KVS
peer connection where that is the best available path.

## Terms

- **RTC session**: A WebRTC peer session established through AWS KVS signaling.
- **media RTC session**: An RTC session that carries the unit video track and
  may also carry the MCP data channel.
- **control-only RTC session**: A future RTC session that carries MCP data
  channels without a video track.
- **RTC worker**: The native C/C++ process that owns AWS KVS WebRTC, libcamera,
  encoding, peer connections, and local data-channel IPC.
- **MCP session**: A logical MCP client session. It is independent from the
  transport and can arrive over WebRTC data channel or MQTT.
- **active control**: The single MCP session currently allowed to execute
  actuator tools such as `cmd_vel.publish`.

## Agreed Decisions

### Rust Owns Control Logic

The Rust unit daemon should own motor control, MCP tool behavior, active control
state, command validation, and software watchdogs.

Reason: these responsibilities are application policy. They should not live in
the native WebRTC worker, because the same policy must apply over MQTT fallback
and future transports.

### Native Worker Owns RTC And Camera

The KVS/WebRTC and camera path remains native for the next implementation
phases.

Reason: the current AWS KVS WebRTC sender and Raspberry Pi camera path already
depend on native libraries. Replacing that with pure Rust would add WebRTC,
AWS signaling, ICE, camera, and encoder risk before the daemon migration has
proven the control model.

### Video Failure Falls Back To REDCON 2

For the current video-capable `unit`, a control-only WebRTC backup is not part
of the next implementation.

In Phase 2a, MCP remains MQTT-only even when video is ready and REDCON reaches
`1`. In the later WebRTC-MCP phase, MCP may prefer the WebRTC data channel on
the media RTC session. When video is unavailable, the unit remains at REDCON `2`
and MQTT MCP control is acceptable.

Reason: this keeps the current product behavior clear. Video readiness remains
the difference between REDCON `2` and REDCON `1`, while MCP availability remains
separate from video availability.

### MQTT Remains Mandatory Fallback

Every MCP-capable device must continue to expose MQTT JSON-RPC as a fallback
transport.

Reason: connection success is more important than lowest latency. MQTT is also
the acceptable REDCON `2` control path when video is not ready.

### WebRTC Transport Becomes Preferred After Phase 2b

For video-capable units after Phase 2b, the preferred MCP transport is WebRTC
data channel on the media RTC session whenever video is available.

Reason: a video consumer can receive media and send control commands over the
same AWS KVS WebRTC session. This is the cleanest low-latency path for the
operator and for future near-realtime cloud consumers. This is explicitly not
part of Phase 2a.

### No Second KVS Channel In The Unit Migration

The unit migration should not add a second KVS signaling channel for control
backup.

Reason: a second channel is conceptually valid for future no-video or
control-only devices, but it adds another RTC lifecycle, status path, and client
selection problem. For the current unit, REDCON `2` plus MQTT fallback is enough
when video is unavailable.

If a future device needs control-only WebRTC, it should use a distinct signaling
channel, not share the media signaling channel with a separate master.

### Active Control Replaces Lease Override Modes

The MCP server should model actuator authority as a single active control slot.

Many sessions may observe capabilities. Exactly one session may be active
controller. Only the active controller may execute control tools. Manual
operator takeover is an explicit switch of active control from one session to
another, not concurrent control and not a special "override command" mixed into
every control call.

Reason: this cleanly separates session identity, transport, and actuator
authority. A cloud worker can normally control, a human operator can observe,
and the human can explicitly take active control when needed.

### Commands Stay Request/Response

Actuator commands should remain blocking request/response at the protocol
boundary. The daemon validates active control, command shape, safety state, and
rate limits before accepting a command.

State publication remains event-driven: active-control changes, drive state,
video status, and transport status can be emitted asynchronously.

Reason: motor control over the internet should behave like explicit accepted or
rejected commands. Event-driven state propagation is useful, but fire-and-forget
actuation would blur command authority and safety behavior.

## Target Shape

```text
Rust unit daemon
  board shadow and retained capability state
  MCP core: sessions, tools, active control, watchdogs
  MQTT JSON-RPC transport
  motors and cmd_vel mixing
  video/MCP descriptor and status publication
  native rtc-worker supervision

native rtc-worker
  AWS KVS WebRTC master
  libcamera capture when video is enabled
  H.264 encode and media track
  WebRTC data channel acceptor (Phase 2b)
  local IPC bridge to daemon MCP core (Phase 2b)

browser or cloud consumer
  AWS KVS viewer
  video receiver when media is available
  MCP client over WebRTC data channel when available
  MQTT MCP fallback when WebRTC is not available
```

The daemon owns all decisions about whether MCP is available, which transport is
advertised, which session is active controller, and whether a command is safe to
apply. The RTC worker reports readiness and forwards WebRTC data-channel
messages; it does not decide command authority.

Phase 2a uses only the media portions of this shape. The RTC worker reports
readiness/errors through stdout/stderr markers, and the daemon preserves the
existing MQTT-only MCP descriptor.

## REDCON Behavior

The REDCON ladder remains:

- `4`: BLE reachable, unit is in sleep state.
- `3`: BLE reachable and unit stack power is enabled.
- `2`: board and MCP are available.
- `1`: board, MCP, and video are available.

MCP remains a REDCON `2` capability. Video remains the additional capability
required for REDCON `1`.

In Phase 2a, the daemon advertises MQTT-only MCP control regardless of video
status. In Phase 2b, when the RTC media path is ready, the daemon can advertise
MCP WebRTC data channel as the preferred transport. When the media path is not
ready, the daemon should advertise MQTT-only MCP control and the device should
remain at REDCON `2` if board and MCP are otherwise healthy.

## MCP Transport Descriptor Direction

Phase 2a must preserve the existing MQTT-only descriptor. The next descriptor
version for Phase 2b should make transport choice explicit and ordered by
priority.

For video-ready units:

```json
{
  "serviceId": "mcp",
  "mcpProtocolVersion": "next",
  "transports": [
    {
      "type": "webrtc-datachannel",
      "priority": 10,
      "sessionKind": "media",
      "signaling": {
        "provider": "aws-kvs",
        "channelName": "<device_id>-board-video",
        "region": "<aws-region>"
      },
      "label": "txing.mcp.v2"
    },
    {
      "type": "mqtt-jsonrpc",
      "priority": 100,
      "topicRoot": "txings/<device_id>/mcp"
    }
  ]
}
```

For REDCON `2` units without ready video:

```json
{
  "serviceId": "mcp",
  "mcpProtocolVersion": "next",
  "transports": [
    {
      "type": "mqtt-jsonrpc",
      "priority": 100,
      "topicRoot": "txings/<device_id>/mcp"
    }
  ]
}
```

A future no-video device can add a `sessionKind: "control"` WebRTC transport
when it has a control-only RTC worker and a dedicated signaling channel.

## Active Control Model

The daemon maintains one active control slot:

```json
{
  "activeControl": {
    "sessionId": "session-id",
    "actor": "cloud-worker",
    "transport": "webrtc-datachannel",
    "sinceMs": 1770000000000,
    "expiresAtMs": 1770000005000,
    "epoch": 42
  }
}
```

Rules:

- many sessions may connect and read state
- only the active session may execute actuator tools
- active control has a TTL and must be renewed
- active control is cleared when the session closes or expires
- every active-control switch increments `epoch`
- every active-control switch forces motors to neutral before accepting commands
  from the new active session
- commands from a previous active-control epoch are rejected

Candidate MCP methods:

- `control.get_state`
- `control.activate`
- `control.renew_active`
- `control.release_active`
- `control.deactivate_session`
- `cmd_vel.publish`
- `cmd_vel.stop`
- `robot.get_state`

The exact method names can change with the breaking MCP protocol version, but
the authority model should stay centered on active control rather than
transport-specific lease override modes.

## Implementation Phases

### Phase 1: REDCON 3 In Rust Daemon With MQTT Control

Goal: prove that the Rust unit daemon can own board control policy without
WebRTC or video.

This phase starts from the REDCON `3` wakeup-state daemon path. MCP control
itself remains a REDCON `2` capability in the public contract; do not redefine
REDCON `3` to mean MCP is available. Once the Rust daemon publishes healthy
board and MCP capability state, the device may naturally derive REDCON `2`.

Scope:

- move motor control into the Rust daemon
- implement `cmd_vel` mixing and software watchdogs in Rust
- implement MCP core in Rust
- expose MCP over MQTT JSON-RPC
- publish retained MCP descriptor/status topics
- publish `mcp` named-shadow mirror or keep the existing rig mirror contract
  updated as appropriate for the current ownership boundary
- publish board and MCP retained v2 capability state so REDCON can reach `2`
  when the board and MCP daemon are healthy
- keep video unavailable

Expected operating state:

- REDCON `3` works from the Rust daemon path
- MQTT control works when the board and MCP capability state are healthy enough
  for the device to derive REDCON `2`
- motor commands are accepted only from the active control session
- software watchdog stops motors on command silence, session close, active
  control expiry, or daemon shutdown

Notes:

- No native RTC worker dependency is required in this phase.

Current status as of 2026-05-16:

- Implemented in the Rust unit daemon:
  - MCP protocol version `2026-05-16`
  - MQTT JSON-RPC MCP transport on
    `txings/<thing>/mcp/session/<sessionId>/c2s` and `.../s2c`
  - tools `control.get_state`, `control.activate`,
    `control.renew_active`, `control.release_active`,
    `cmd_vel.publish`, `cmd_vel.stop`, and `robot.get_state`
  - one active-control slot with TTL, epoch checks, stale-epoch rejection,
    no-active rejection, and no takeover in Phase 1
  - motor ownership, Twist validation, tank mixing, PWM/GPIO output, and
    watchdog neutralization on command silence, active expiry, MQTT loss, and
    shutdown
  - retained MCP descriptor/status publication and `mcp` named-shadow mirror
  - retained v2 capability publication for `board=true`, `mcp=true`,
    `video=false` while healthy and false/offline on shutdown
- Implemented in AWS/IAM:
  - daemon permissions for retained MCP topics, MCP session receive/publish,
    `mcp` named-shadow updates, and retained capability state
  - operator/browser policy coverage for MCP descriptor/status reads and
    session `s2c` subscriptions
  - cloud time runtime MCP IoT rule is scoped to `time-*` thing names so it
    cannot answer unit MCP topics
- Implemented in the web app:
  - unit drive capability is enabled at REDCON `1` and `2`
  - board video remains enabled only at REDCON `1`
  - REDCON `2` renders the non-video drive panel with track gauges, battery,
    board/BLE status, and MQTT transport indicator
  - robot-state polling and keyboard teleop are tied to active unit detail plus
    drive capability and shadow connection, not video expansion
  - stale/default MCP unavailable shadow state no longer blocks MQTT MCP startup
  - robot-state polling continues while motion is active so watchdog stops are
    reflected back in the UI
- Implemented in Sparkplug derivation:
  - live daemon board/MCP capability state can derive REDCON `2` even if the BLE
    power capability is temporarily stale false
  - REDCON `1` remains non-convergent in Phase 1 because video capability stays
    false

Open Phase 1 rollout and validation items:

- Deploy a new rig `sparkplug-manager` component/release containing the REDCON
  derivation fix.
- Deploy the AWS stack updates for the operator MCP policy and scoped cloud-time
  MCP IoT rule.
- Deploy the updated web bundle.
- Deploy/restart the unit daemon release that contains the Phase 1 daemon
  implementation.
- Complete hardware validation on a clean unit install:
  - command REDCON `4` to sleep, then command REDCON `1`; the expected Phase 1
    outcome is convergence to REDCON `2` and a REDCON `1` convergence timeout
    because video is unavailable
  - drive over MQTT MCP without video
  - confirm neutral behavior on key stop, blur, command silence, active expiry,
    MQTT loss, and daemon shutdown
  - confirm the UI reflects daemon watchdog stops through `robot.get_state`
    polling

### Phase 2a: Video Capability With MQTT-Only MCP

Goal: reach the current Python board runtime behavior with the Rust daemon as
the control owner and a separate native KVS worker as the RTC/media owner,
while keeping MCP on MQTT only.

Scope:

- install `txing-board-kvs-master` as a separate mise-managed release asset
  beside `txing-unit-daemon`
- supervise the native `txing-board-kvs-master` from the Rust daemon
- keep camera capture, H.264 encode, and AWS KVS master behavior in the native
  worker
- publish retained video descriptor/status topics from the daemon
- mirror video descriptor/status into the `video` named shadow according to the
  current reader contract
- keep the MCP descriptor transport-neutral in shape but MQTT-only in content
- publish video retained v2 capability state so REDCON can reach `1` when the
  video worker is ready

Expected operating state after phase 2a:

- browser operator can open the existing unit video route
- operator can see video through AWS KVS WebRTC
- operator can control from the browser over MQTT MCP
- behavior is at least equivalent to the current Python control plus
  `kvs_master` implementation, except MCP over WebRTC remains intentionally
  deferred

Notes:

- Phase 2a iteration should use the `Unit Daemon Feature Prerelease` GitHub
  workflow from a pushed `feature/*` branch. The workflow publishes both
  `txing-unit-daemon-linux-aarch64.tar.gz` and
  `txing-board-kvs-master-linux-aarch64.tar.gz`; boards can then opt into the
  feature channel for validation without publishing a stable project release.
- The worker should be treated as a child process with bounded restart/backoff
  and clear status reporting.
- Stderr/stdout markers remain the current worker status input for readiness,
  viewer connection, and errors.
- Promote to a stable release only after Phase 2a board validation passes.

### Phase 2b: MCP Over Video WebRTC

Goal: add WebRTC data-channel MCP only after the Rust daemon owns video worker
supervision and video capability publication.

Scope:

- connect worker WebRTC data-channel messages to the Rust MCP core through local
  IPC
- advertise MCP WebRTC data channel first only when media RTC is ready
- advertise MQTT fallback always
- make browser transport switching deterministic and observable

### Phase 3: Channel Switching And Responsibility Control

Goal: finish the MCP v2 authority model and make multi-consumer behavior
deterministic.

Scope:

- finalize the breaking MCP descriptor/protocol version
- implement active control state and epoch enforcement
- implement explicit active-control switching between sessions
- stop motors on every active-control switch
- reject actuator commands from non-active sessions
- publish active-control state through MCP status and `robot.get_state`
- make WebRTC/MQTT transport switching deterministic and observable
- define browser UI behavior for manual takeover from a cloud worker
- harden disconnect, expiry, reconnect, and fallback behavior

Expected operating state:

- multiple sessions can observe the same device
- one session at a time controls motors
- a manual operator can explicitly take active control from a cloud worker
- the displaced session remains connected for observation but cannot actuate
- stale commands from the old active session or old epoch are rejected
- fallback from WebRTC to MQTT does not create a second controlling authority

## Future Cloud Session Consumer

A cloud session consumer fits this architecture as another KVS viewer and MCP
session.

For video-capable units in REDCON `1`, the cloud worker connects to the media
RTC session, receives video, and sends MCP commands over the WebRTC data channel.
The human operator can connect at the same time as an observer. If the human
operator takes active control, the daemon switches the active control slot from
the cloud worker session to the operator session, stops motors, increments the
control epoch, and rejects further actuator commands from the cloud worker until
control is switched back.

For REDCON `2` or video-unavailable states, the cloud worker may still use MQTT
MCP if that is acceptable for the task. The architecture does not require a
control-only WebRTC channel for the current unit, but leaves room for future
device types to advertise one as a separate transport.

The near-realtime cloud consumer should initially use the same AWS KVS/WebRTC
model as the browser/operator path. A native C/C++ worker is the lowest-risk
consumer implementation because it matches the current AWS KVS WebRTC native
surface. A Rust application can still own policy and supervision around that
native worker. Pure Rust WebRTC/KVS integration should be treated as a separate
future investigation rather than a dependency of the unit daemon migration.

## References

- [Board component guide](./components/board.md)
- [Unit board video contract](../devices/unit/docs/board-video.md)
- [Unit device-rig shadow contract](../devices/unit/docs/device-rig-shadow-spec.md)
- [Sparkplug lifecycle](./sparkplug-lifecycle.md)
