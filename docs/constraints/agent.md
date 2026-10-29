# Agent constraints

Status: approved 2026-10-18 for
[milestone 10](https://github.com/mparkachov/txing/milestone/10).
Duration amended 2026-10-23: the current-stage maximum is fifty minutes;
see the [finding and limitation decision](agent-session-limit.md).
These constraints govern the replacement described in
[Agent](../components/agent.md). They supersede the earlier Go/Fargate and
arm-triggered QGroundControl designs; they are not a claim of implementation.

## Product and ownership

- Use **agent** consistently. It is the AI counterpart of Office, with an
  interchangeable operator behavior consuming video/telemetry and issuing
  authorized actions. QGroundControl is the first manual behavior.
- Support TBot only in this milestone. Resolve registered Thing type; reject
  unsupported types before opening sessions. Keep device mapping in a small
  compiled-in profile and pass explicit configuration to transport.
- Keep rig/witness lifecycle projection and board authority unchanged. MAVLink
  runs at born REDCON 2/1; video at REDCON 1. Poll lifecycle every two seconds;
  inactivity/death or fifteen seconds without verification initiates shutdown.
- Preserve independent session recovery. Video loss or shutdown must not reset
  healthy MAVLink or destroy their shared SDK lifetime.

## Implementation boundary

- All new agent runtime and controller production code is C++. Link the pinned
  AWS KVS WebRTC C SDK directly into one agent process; use AWS SDK for C++
  credential/API facilities and libwebsockets for HTTP/WebSocket support.
- The 2026-10-29 operator amendment permits a stop-only shutdown watch in the
  existing Go witness Lambda. It reads agent assignments, never writes the agent
  shadow or launches agents, and follows the [watch contract](agent-watch.md).
- Use the same application source on macOS and Linux ARM64. Remove the Go
  supervisor, native viewer executable, credential pipes, and custom worker IPC.
  Build/release tooling is CMake, Just, and minimal POSIX shell; no new agent
  Go/Python production or publication helpers. Tests may use other languages.
- Deliver encoded frames with codec, presentation timestamp, and local receipt
  time to the operator boundary before counting/discarding. Bounded queues
  prevent slow video consumers from blocking control or exhausting memory.
- Prove operator substitution with a test behavior that receives both streams
  and sends an authorized action. Do not add model inference, decoding,
  autonomous motion, dynamic plugins, or a speculative command language.
- Directly replace milestone-specific agent/Fargate code and obsolete release
  paths. Preserve deployed device protocols, independent connection fixes,
  and shared SDK resources used elsewhere. No wholesale history reversal,
  parallel implementation, or compatibility wrapper.

## Control and manual clients

- Observation is the default. Explicit control requests a free board lease with
  `takeover=false`. After grant, allow the full MAVLink protocol, including
  pre-arm configuration; preserve signed/unfamiliar complete frames exactly.
- The operator session owns control across arm/disarm cycles. Arm/disarm
  commands do not acquire/release the lease.
- Release on five-second manual-client inactivity, disconnect, WebRTC loss,
  lease loss, lifecycle shutdown, or process shutdown. Never automatically
  reacquire after loss. Preserve the deployed five-second lease, epochs, wire
  envelopes, one-MAVLink-2-frame-per-message representation, and board safety.
- Local run and cloud attachment bind loopback, default `127.0.0.1:14551`.
  QGroundControl listens on 14550. Send telemetry immediately to its configured
  endpoint; recognize initial MAVLink 1 heartbeats for client presence without
  forwarding MAVLink 1 over the board's MAVLink 2 channel.
- Cloud attachment uses authenticated WebSocket and one manual client per
  agent. It reuses the cloud agent's device connection and control lease.
- Local execution uses the SDK credential chain and refresh, logs status, and
  neither requires agent infrastructure nor invokes its controller nor writes
  its operational shadow. Preserve useful diagnostics without exposing secrets.

## Cloud and cost

- Device types opt in through the normal `agent` capability declaration and
  its named shadow. TBot currently declares it; other device types do not.
  Cloud authorization requires that registry capability and the rig-projected
  `capability.agent=true` at born REDCON 1/2. Explicit false or capability removal
  stops the run; missing/invalid evidence fails closed. Agent cloud readiness
  never gates the physical REDCON that enables it.

- Use Lambda MicroVMs in `eu-central-1`. Initialize identities, credentials,
  and device sessions after snapshot restoration. Never snapshot live sessions.
- Disable automatic idle suspension/resumption. A human attachment is not a
  prerequisite for an active cloud agent.
- One authorized agent per active supported device; current lifecycle events
  plus a one-minute repair pass handle duplicates, missed events, interrupted
  starts, orphaned runs, and stale assignments with bounded retries.
- Persist a fifty-minute (3000-second) budget per device activation across replacements.
  Expiry releases control and stops cloud operation until a subsequent
  inactive-to-active transition; no automatic rollover.
- The 2026-10-28 operator decision accepts fail-closed recovery if the
  controller misses an inactive interval: keep the expired activation until
  the controller directly observes a later verified inactive-to-active
  transition. An incomplete or unreadable projection is not an inactive
  observation. Keep the witness projection unchanged.
- New disposable requests also cap hosting at 3000 seconds. This is an upper
  bound, not an uninterrupted-session guarantee: the board's existing
  fifty-five-minute credential renewal can interrupt an older board session
  earlier. The board renewal repair and the former eight-hour target are deferred.
- The C++ controller alone writes the cloud `agent` shadow. Keep run identity,
  release, lifecycle/deadline, HTTPS endpoint, and sampled runtime status.
  Separate lifecycle and connection state; superseded runs cannot restore a
  usable endpoint. The optional shadow never affects REDCON.
- No idle MicroVM compute, dedicated VPC/NAT, ECR, ECS, or always-on agent
  networking. Retained artifacts/logs/snapshots and usage-based API/event costs
  are allowed. Do not promise zero total AWS charges.
- Prompt normal shutdown has an independent witness repair path with a
  two-minute grace and one-minute schedule. This operator-approved delayed
  convergence depends on AWS service availability; live evidence must show
  actual terminal VM state after a controller failure.

## Acceptance and publication

- A disposable, operator-run MicroVM connectivity probe is a prerequisite to
  full cloud automation. It proves both real streams, role credentials,
  authenticated attachment, ICE/TURN behavior, and operation beyond fifteen
  minutes. Failure stops cloud implementation for architectural review.
- Real secured/lifted-TBot local QGroundControl acceptance precedes production
  cloud publication. The early disposable probe is not production publication
  or permission to enable lifecycle automation.
- Real cloud acceptance repeats control/failure checks through attachment,
  demonstrates startup without a human client, tests the duration boundary,
  and proves termination to zero running MicroVMs. Mocks/prepared commands do
  not satisfy physical or live cloud acceptance.
- Releases are immutable and versioned. Initial infrastructure uses operator-run
  CloudFormation; normal publication uploads an S3 artifact, waits for an image
  build, and selects the successful version for later launches. Failed builds
  leave the previous selection intact; running agents keep their version.
- Document base-image rebuild requirements, provenance, packaging,
  repeatability, and storage costs. Immediate replacement requires explicit
  disarm-and-drain steps.
- No automatic commits, AWS mutations, flashing, or legacy-resource cleanup.
  Prepare operator commands and evidence requirements. Initial migration must
  disable old triggers and drain old tasks before enabling the replacement.

