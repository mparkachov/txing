# Agent

Status: approved replacement design, 2026-10-18. Implementation and acceptance
are tracked in [milestone 10](https://github.com/mparkachov/txing/milestone/10).
This document describes the target architecture, not completed functionality.
The committed Go/Fargate implementation is superseded and remains pending
removal through the milestone.

## Purpose

The agent is the AI counterpart of Office. Office connects device observations
and actions to a human; the agent connects them to an operator behavior that
can later be supplied by an AI model. This milestone establishes the first
working skeleton, using QGroundControl as its manual operator behavior.

One C++ implementation runs natively on a development Mac and in AWS Lambda
MicroVMs. The cloud starts an agent automatically for a supported active device,
even when no human is attached. TBot is the only supported profile in this
milestone. The agent receives video and telemetry, exposes explicit control
authority, and sends actions through the existing device protocol.

Video arrives at the operator as timestamped encoded frames and is counted and
discarded there. Model selection, decoding, inference hosting, training, and
autonomous motion are later work. The runtime must make that later substitution
possible without rebuilding its transport or hosting.

## Replacement boundary

Build the replacement under top-level `agent/` from the committed baseline
after the operator's reset. Replace milestone-specific agent implementation,
Fargate infrastructure, worker IPC, and obsolete release paths directly.
Do not retain parallel runtimes or compatibility wrappers.

Preserve the independently committed board, rig, and Office connection fixes;
the board's deployed MAVLink/video protocols; and the shared SDK pin and build
resources already consumed by other components. Removing the old implementation
does not authorize reverting whole historical commits. The existing optional
`agent` named shadow remains the cloud diagnostic entry point, but its
ECS/public-UDP-specific schema is replaced.

## Runtime responsibilities

| Responsibility | Owns |
| --- | --- |
| Device session | Registered device profile, independent WebRTC connections, telemetry/video delivery, and the board control lease |
| Operator behavior | Observations and actions; initially the manual QGroundControl behavior |
| Hosting | Local startup or MicroVM lifecycle, credentials, execution authorization, and diagnostics |

The production runtime is one `txing-agent` process. It links the pinned AWS
KVS WebRTC C SDK directly; there is no Go supervisor, separate native viewer,
credential pipe, or custom process protocol. Initialize the SDK once for the
process and preserve that lifetime while either session exists.

Use the AWS SDK for C++ for AWS APIs and credential providers. Adapt its
credentials to the KVS provider in process, including static and refreshable
credentials. Use the SDK's signaling and reconnection facilities; application
code owns bounded peer recovery and device lifecycle rather than a competing
signaling implementation. Reuse libwebsockets for HTTP/WebSocket support.
Build with CMake, Just, and minimal POSIX shell tooling. No new agent Go or
Python production code, including controller or publication helpers, is in
scope; tests may use other languages.

Transport receives explicit channel, region, media/data role, and data-channel
label. It neither derives TBot names nor parses MAVLink nor manages cloud runs.
Keep diagnostics actionable and free of secrets: retain SDK errors and
operation context rather than replacing all failures with a generic exit.

### Operator interface

The operator receives telemetry, encoded video, connection changes, and control
loss. It can request control, send MAVLink, and release control. Video includes
codec, presentation timestamp, and local receipt time; timestamps retain their
respective clock meanings and do not imply cross-stream synchronization.

Use bounded queues with explicit overload behavior. Slow video consumption
cannot delay control or cause unbounded memory growth. SDK callbacks must not
execute blocking operator work.

The manual operator forwards QGroundControl traffic and counts/discards video.
Discard happens at the operator boundary, not inside the transport callback.
A test operator must consume both observation types and issue an authorized
action through the same interface. Do not introduce a dynamic plugin system,
generic robot-command language, or production placeholder AI framework.

### Profiles and lifecycle

Resolve the registered AWS IoT Thing type before opening sessions. A small
compiled-in TBot profile supplies channel templates and activation rules,
validated against its manifest:

- `<thing-id>-mavlink`: ordered reliable data channel `txing.mavlink.v1`,
  active at born REDCON 2 or 1.
- `<thing-id>-board-video`: receive-only video, active at born REDCON 1.
- REDCON 3/4, device death, or expired execution authorization initiates shutdown.

Unsupported registered types fail before session creation. A name prefix alone
does not establish support. Rig and witness remain lifecycle authorities.

Poll lifecycle every two seconds and stop after fifteen seconds without
authoritative verification. Video and MAVLink recover independently; returning
from REDCON 1 to 2 closes only video. A transient connection problem must not
replace the entire cloud process or erase another connection's error.

### Control authority

Follow the [board MAVLink contract](../contracts/board-mavlink.md).
Observation is the default. Explicit manual control requests a free lease with
`takeover=false`; busy ownership remains intact. After grant, the operator
can forward the full MAVLink protocol, including pre-arm parameter traffic.

The operator session owns the lease. Arm and disarm are ordinary MAVLink
commands; neither acquires nor releases control. Release on manual-client
inactivity, disconnect, WebRTC loss, lease loss, lifecycle shutdown, or process
shutdown. Never reacquire automatically after loss. Keep the existing
five-second lease and manual-client inactivity boundary, epochs, operation
names, one-frame-per-binary-message representation, and board safety behavior.
Attempt graceful release before destroying a usable connection; board lease
expiry remains the fallback when the link is lost.

Preserve complete MAVLink 2 frames byte-for-byte, including signatures and
unfamiliar message types. Validate framing without turning the generated
dialect bindings into a tunnel allowlist. Reuse the repository's pinned
generated bindings where message interpretation is needed.

## Native operation

The public commands are target interfaces to implement:

| Command | Behavior |
| --- | --- |
| `just agent::build` | Build/cache the native executable under repository `tmp/` |
| `just agent::run <thing-id> [udp-port] [--control]` | Build if needed and run the complete agent locally in the foreground |
| `just agent::attach <thing-id> [udp-port] [--control]` | Build if needed and connect localhost QGroundControl to the existing cloud agent |
| `just agent::test` | Run relevant automated checks |
| `just agent::deploy` | Operator-run initial CloudFormation deployment |
| `just agent::publish <version>` | Operator-run publication of an immutable agent release |

Both manual commands bind `127.0.0.1:14551` by default. QGroundControl listens
on UDP 14550 and sends to the chosen agent listener port. The optional positional
port changes the agent listener. Report invalid or occupied ports clearly.

Send available telemetry immediately to the configured QGroundControl endpoint;
do not wait for an incoming MAVLink 2 heartbeat. Recognize initial MAVLink 1
heartbeats for client presence and verify QGroundControl's negotiation to
MAVLink 2. Recognition does not permit MAVLink 1 frames on the board's deployed
MAVLink 2 data channel.

Local execution uses the AWS SDK credential chain and configured region,
including supported profiles and refreshable credentials. Document native
macOS prerequisites and cache a verified TLS trust anchor under repository
scratch space. Local execution uses existing device IoT/KVS resources but does
not require agent infrastructure, invoke the controller, or write the cloud
`agent` shadow. Status is logged locally.

## Cloud operation

Use Lambda MicroVMs in `eu-central-1` with the same runtime source compiled for
Linux ARM64. AWS documents Frankfurt support, an eight-hour maximum lifetime,
and authenticated HTTPS/WebSocket ingress. Raw public UDP is not the cloud
interface. See the [regional announcement](https://aws.amazon.com/about-aws/whats-new/2026/08/lambda-microvms-5-additional-regions/),
[runtime documentation](https://docs.aws.amazon.com/lambda/latest/dg/microvms-launching.html),
and [networking documentation](https://docs.aws.amazon.com/lambda/latest/dg/microvms-networking.html).

Initialize unique device/run identity, runtime credentials, and WebRTC after
snapshot restoration through the run hook. Never snapshot live device sessions.
Disable automatic idle suspension and resumption: an active device can require
an operator even when nobody is attached through the HTTPS endpoint.

### Controller and authorization

A small C++ controller Lambda responds to completed projected lifecycle changes
and a one-minute repair pass. It verifies current registered type/lifecycle,
starts at most one authorized agent per supported active device, and terminates
inactive, failed, or superseded runs. Launches are idempotent and retries are
bounded. Repair handles missed events, interrupted launches, and orphaned runs.

Persist launch identity and the device activation deadline. An activation
allows at most eight hours of cloud operation, including replacement processes.
Retries, new image versions, process replacements, and delayed events cannot
reset that allowance. At expiry, release control and stop; permit another
activation only after a subsequent inactive-to-active lifecycle transition.
Do not implement automatic rollover.

The cloud runtime verifies its assignment in addition to device lifecycle.
Stale assignments cannot retain control or advertise a usable attachment.
Connection recovery belongs to the runtime: a temporary video/MAVLink
interruption does not justify replacing a healthy MicroVM.

The controller is the sole writer of the `agent` named shadow. Its replacement
contract records cloud run identity, release, lifecycle/deadline, HTTPS endpoint,
and sampled runtime status. Runtime status exposes individual connection state,
video receipt, control state, and actionable errors for controller sampling.
Separate cloud lifecycle from connection readiness and retain freshness and run
identity when interpreting sampled status. Old generations cannot restore a
usable endpoint. Local runs never participate in this ownership.

Office continues to show the optional shadow in Debug. It remains outside
REDCON capability derivation and must not block ordinary device use when absent.
Update its schema/default and relevant consumers directly during implementation;
do not maintain an ECS-shaped shadow compatibility layer.

### Manual attachment

`attach` discovers the current cloud run, obtains a short-lived port-scoped
AWS authentication token, and forwards localhost MAVLink over an authenticated
WebSocket. It does not create another device WebRTC session or another board
lease. Allow one manual attachment per agent. The cloud agent's manual behavior
uses the same explicit-control and loss policy as local execution.

Cloud startup remains useful with no attachment: it observes telemetry and
delivers video to the operator. Token expiry, attachment loss, or client
inactivity cannot leave manual control active indefinitely or silently reacquire
it after reconnect.

### Cost and release model

Use managed public networking, S3 artifacts, IAM, CloudWatch, the C++ controller,
and lifecycle triggers. Remove dedicated VPC/NAT, public-IP management, ECR,
and ECS task definitions. Inactive devices leave no running MicroVMs or
always-on agent networking resources. Artifact storage, logs, snapshots, and
usage-based service calls remain billable; this is not a zero-total-cost claim.

Keep immutable `agent` releases. AWS builds a MicroVM image from an S3 package
containing a Dockerfile and application artifacts. The operator's publish command
uploads the selected release, waits for a successful build, and selects that
version for subsequent launches. A failed build preserves the previously selected
release. New publication does not interrupt existing runs. See
[MicroVM image management](https://docs.aws.amazon.com/lambda/latest/dg/microvms-images.html).

Separate initial CloudFormation deployment from ordinary application publication.
Document managed base-image expiry/rebuild requirements, artifact provenance,
repeatability, runtime dependency packaging, and retained storage costs.
Publication must not introduce agent-owned Python tooling or a second
application release implementation.

## Validation gates and rollout

First prove native observation and operator substitution using real SDK peers.
Then run the same C++ application in a disposable MicroVM before building full
cloud automation. Prove both KVS sessions, real video frame delivery, MAVLink
telemetry, execution-role credentials, authenticated WebSocket attachment,
ICE/TURN behavior, and continuous operation beyond fifteen minutes.

The probe is operator-run and does not authorize production lifecycle
automation. If feasibility fails, stop cloud implementation and revisit hosting;
do not silently add Fargate, NAT, or another runtime. The service documentation
does not prove this workload works in that environment.

Automated acceptance covers bounded queues, credentials/refresh, unsupported
types, independent recovery, graceful shutdown, loopback/occupied ports,
QGroundControl bootstrap, framing/signature preservation, explicit lease
ownership, contention, inactivity, loss and stale epochs, current run fencing,
duplicate/out-of-order lifecycle events, interrupted launches, orphan cleanup,
and the activation cap without restart loops. Preserve error details after long
healthy periods. Validate native macOS and Linux ARM64 artifacts and provenance.

Real local acceptance gates production cloud publication. Record the source
revision, versions, QGroundControl settings, device, logs, and observations for
telemetry, parameter retrieval, video receipt, arm/drive/disarm/re-arm, Office
contention, client/WebRTC loss, and REDCON transitions on a secured, lifted TBot.

Final cloud acceptance repeats the physical flow through `attach`, proves
automatic observation without a human attachment, and verifies zero running
MicroVMs after inactivity. Exercise the eight-hour boundary with an accelerated
test configuration. Prepared commands, mocks, and cross-compilation do not
substitute for recorded native, cloud, or physical acceptance.

For initial replacement, the operator disables old triggers, disarms/releases
control, drains old tasks, and manually removes obsolete agent resources as
needed before enabling the new deployment. Do not modify cloud MCU networking.
Ordinary publication leaves existing runs on their current release; immediate
adoption requires explicit disarm-and-drain replacement. No automatic commits,
AWS mutations, firmware flashing, or legacy-resource cleanup are authorized.

## References

- [Agent constraints](../constraints/agent.md)
- [Board MAVLink contract](../contracts/board-mavlink.md)
- [Board video](board-video.md)
- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [TBot manifest](../../devices/tbot/manifest.toml)
- [Lambda language boundary](../aws-lambda-boundary.md)
- [Execution and release boundaries](../agent-guidance/editing-boundaries.md)

