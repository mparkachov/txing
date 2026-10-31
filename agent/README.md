# Agent

Device types opt in through the `agent` capability and its corresponding named
shadow. TBot currently declares it. Registry membership and the rig-projected
`capability.agent` availability authorize execution; the controller owns the
shadow's actual cloud run status. Devices without the capability cannot launch
or attach an agent. Missing availability fails closed until the updated rig
publishes verified lifecycle evidence. See the
[capability rollout](../docs/constraints/agent-rollout.md#agent-capability-rollout).

The C++ foreground observer is implemented for
[#164](https://github.com/mparkachov/txing/issues/164). Native macOS build,
automated checks and active TBot observation passed, including independent
peer recovery and verification-timeout checks against real streams. The native
QGroundControl UDP operator is implemented for
[#166](https://github.com/mparkachov/txing/issues/166); its loopback, lease and
real SDK integration checks are recorded in the
[manual acceptance report](../docs/agent-manual-acceptance.md).
Physical TBot acceptance is recorded in
[#167](https://github.com/mparkachov/txing/issues/167), including its unresolved
intermittent transport-timeout limitation. Cloud automation and publication
are separate issues.

The disposable MicroVM feasibility experiment was accepted under
[#165](https://github.com/mparkachov/txing/issues/165). `just agent::probe-package`
prepares its source-only image context; the [operator runbook](../docs/agent-microvm-acceptance.md)
describes resource creation, role/ingress checks, sustained observation and cleanup.
Live MicroVM feasibility is accepted within the
[current-stage fifty-minute limit](../docs/constraints/agent-session-limit.md).
The board's credential renewal can interrupt sessions earlier; the runbook
records that limitation. The #168 C++ controller, cloud host and attachment are
implemented. Operator-run source-build acceptance covers automatic telemetry/video,
authenticated QGC attachment, explicit lease ownership, client-loss fencing and
terminal shutdown; see the [cloud evidence](../docs/agent-cloud-build-validation.md).
The diagnostic `0.0.0` test build is unpublished. Immutable publication remains
#169 and final released-cloud physical acceptance remains #170. Launches are
disabled after the controlled test.

Read the [design](../docs/components/agent.md),
[constraints](../docs/constraints/agent.md), and
[cloud shadow contract](../docs/contracts/agent-shadow.md) for ownership boundaries.
The implementation has one executable linking the KVS C SDK directly and uses
AWS SDK for C++ credentials and read-only IoT APIs. Local runs never write the
agent shadow or invoke cloud agent infrastructure.

## Native prerequisites

On macOS install the Xcode command line tools, Just, Git, CMake, curl and these
Homebrew formulas manually:

```sh
brew install cmake just openssl@3 libwebsockets srtp libusrsctp log4cplus
```

Linux ARM64 builds use the same application source and require C/C++17 compilers,
CMake 3.24+, Git, curl, OpenSSL, zlib, libcurl, libwebsockets, libsrtp2,
libusrsctp, log4cplus, and their development headers. Native execution on Linux
does not satisfy macOS acceptance. No board build or firmware change is needed.

```sh
just agent::build
just agent::test
just agent::run <registered-tbot-thing-id> --region eu-central-1
```

The foreground run observes and logs; Ctrl-C or SIGTERM releases authority and
closes both sessions. The agent binds `127.0.0.1:14551` and sends telemetry to
QGroundControl at `127.0.0.1:14550` immediately, even before QGC sends anything.
`publish` remains the separate immutable-release workflow in #169.

## Cloud attachment

Once the replacement infrastructure and an accepted image are deployed and
enabled by the operator, use the same QGroundControl link configuration as a
local run:

```sh
just agent::attach <registered-tbot-thing-id>
just agent::attach <registered-tbot-thing-id> 14551 --control
```

Attachment discovers and verifies the current assignment, obtains a token for
port 8081, and forwards to the existing agent rather than opening another
device session. Observation is the default. `--control` makes one free-lease
attempt after QGroundControl presence and telemetry readiness. Only one manual
attachment is accepted. Inactivity, connection loss, assignment loss, token
cutoff or process exit releases manual control without reacquisition. The
client requests a five-minute token and closes at four minutes; start another
explicit attachment to continue. While connected, it periodically checks the
token with an authenticated status request and closes if that check fails. It
does not reconnect and acquire control on its own. The cloud agent observes
telemetry/video before any attachment.

If the controller has missed an inactive interval, or first encounters an
already-active device without a stored activation, it fails closed until it
directly observes a later inactive-to-active transition. Its remaining
50-minute budget is conservatively measured from the last verified inactive
observation. See the [agent shadow contract](../docs/contracts/agent-shadow.md).
Do not delete or reset the controller-owned shadow to manufacture a new budget.

## Preparing cloud artifacts

`just agent::cloud-package` prepares the source-only production MicroVM image
context, including the mandatory assignment-verification startup flag. The
operator runs `just agent::controller-package` with `nerdctl.lima` and its
existing Lima BuildKit engine to build an
ARM64 `provided.al2023` controller ZIP locally. Both recipes write under `tmp/`;
neither calls AWS. The [manual replacement runbook](../docs/constraints/agent-rollout.md)
describes artifact upload, initial disabled deployment, prerequisites,
enablement and draining. The production image and controller ZIP must be built
and checked from the same reviewed source. Do not use the earlier disposable
probe image as the production image.

## Local QGroundControl

In QGroundControl **Application Settings → Comm Links**, use one UDP link with
local/listening port **14550** and remote host **127.0.0.1:14551**. If configuring
that link manually, disable the duplicate UDP auto-connect link. Keep heartbeat
emission enabled under Telemetry/MAVLink settings. QGC supports configuring UDP
local ports and remote hosts in its [Comm Links settings](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/comm_links.html);
heartbeat emission is documented in [Telemetry settings](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/telemetry.html).

```sh
# View telemetry; QGC parameter/configuration writes are blocked.
just agent::run <registered-tbot-thing-id> --region eu-central-1

# Explicit full MAVLink control, including parameter retrieval/configuration.
just agent::run <registered-tbot-thing-id> --control --region eu-central-1

# Different agent listener; change QGC's remote host to 127.0.0.1:15551.
just agent::run <registered-tbot-thing-id> 15551 --control --region eu-central-1

# Different QGC listening port as well; configure its local port to 15550.
just agent::run <registered-tbot-thing-id> 15551 --qgc-port 15550 --region eu-central-1
```

Only the configured loopback QGC source port establishes presence or sends
uplink. Initial valid MAVLink 1 heartbeats establish presence without crossing
the board's MAVLink 2 channel. MAVLink 2 telemetry initiates QGC negotiation;
complete uplink frames, including unfamiliar messages and signatures, retain
their bytes. Each UDP datagram must contain complete frames: no joining across
datagrams. MAVLink 2 CRCs/signatures are validated by the flight controller.

`--control` makes one `takeover=false` lease attempt after client presence and
telemetry readiness. Pre-grant traffic is dropped; QGC's protocol retries can
send it after the grant. A busy Office/other peer remains owner. Once granted,
parameter/configuration, arm, disarm and re-arm traffic use that same lease.
Video is received/count-discarded through the common operator interface; this
command does not display video in QGC.

Control releases after five seconds without valid client traffic, local socket
failure, WebRTC/lease loss, lifecycle shutdown, or process exit. UDP has no close
notification: disconnecting QGC's link or exiting QGC is detected by the same
five-second deadline. Downlink telemetry does not count as client activity.
After a busy/lost/released attempt, reconnecting or sending more traffic never
reacquires control; explicitly restart with `--control` for another attempt.
An observation-only run cannot acquire control.

Ports must be distinct integers from 1 to 65535. If the agent listener is
occupied, stop its other owner or choose another positional port. Diagnostics
include individual connection errors, control changes, observation counts,
rejected datagrams and dropped UDP/enqueue sends. Work is bounded to 32
datagrams per poll, 16 KiB and 32 complete frames per datagram; malformed,
truncated and excessive datagrams are rejected in full.

Rollout is local: run `just agent::test`, configure QGC as above, then start the
foreground command. No board/rig/Office installation or AWS infrastructure
update is needed. The current image accepted in #165 predates this native
adapter; future cloud use needs a newly built image. End native sessions by
fifty minutes under the [current-stage limit](../docs/constraints/agent-session-limit.md).
Real GUI negotiation, parameter, motion, contention and failure acceptance on
a secured lifted TBot remain #167 and have not been performed for #166.

The build, AWS SDK checkout/CRT dependencies, and pinned KVS SDK cache stay under
`tmp/agent-build/`. The first build downloads the SDKs; subsequent builds reuse
objects. CMake uses AWS C++ SDK 1.11.913, verified against commit
`269ff2277f247d78526414b5052729844532362e`, plus the existing shared KVS commit
in `devices/common/kvs/sdk.commit`. The private agent SDK checkout receives
`cmake/kvs-lws-event-loop.patch`: signaling sends wake libwebsockets with
`lws_cancel_service`, then request writable callbacks on its service thread.
The revision-checked, idempotent patch preserves the shared SDK pin and build
resources used by other components. System native libraries remain dynamically
linked; keep their installed versions with acceptance evidence. `TXING_AGENT_BUILD_JOBS`
sets build concurrency (default 4). For explicit CMake options run
`just agent::build <cmake-options>`; rebuild the cache after changing the
native toolchain or dependency prefix. Linux release packaging is later work.

## Credentials and TLS

The application uses the AWS SDK for C++ default provider chain for both IoT
and KVS signing. Use `AWS_PROFILE` to select a configured local profile, and
`AWS_CONFIG_FILE` / `AWS_SHARED_CREDENTIALS_FILE` for explicit file locations.
No CLI credential export, credential pipe, or worker process is used by the
application. Static profiles and environment credentials (`AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`) work; temporary credentials additionally require
`AWS_SESSION_TOKEN`. A manually exported temporary tuple cannot refresh itself.
Use a refreshable SDK provider (profile role/process, SSO with its existing login,
web identity, or execution-role/container credentials) for long runs. Authenticate
that provider before startup; expired or missing credentials cause actionable
errors and lifecycle expiry, rather than granting authority.

The default SDK region/profile configuration is used unless `--region` overrides
it. The provider is consulted again when KVS requests signing credentials; the
adapter preserves expiration and session tokens and rejects expired tuples.
Tests isolate their SDK profiles in repository `tmp/agent-test/`.
See the [AWS credential-provider documentation](https://docs.aws.amazon.com/sdk-for-cpp/v1/developer-guide/credproviders.html).
Native observation used the `mayor` static profile for real IoT/KVS calls. It
has no expiring session tuple to refresh. Rotating and expired providers are
covered by adapter tests; a live SSO/role refresh needs separate evidence when
that provider is selected.

`run` downloads the five public AWS trust roots from the
[Amazon Trust Services repository](https://www.amazontrust.com/repository/),
verifies their published SHA-256 DER hashes and expiry on every invocation, and
assembles `tmp/agent-trust/aws-roots.pem`. It never disables TLS verification.
For a direct binary invocation, run `just agent::trust` and provide its
result via `--ca` or `TXING_AGENT_CA_PATH`. Investigate a failed verification;
do not bypass it. SDK credential providers may also need their normal host trust
store for external identity-provider endpoints.

The identity needs read access to `iot:DescribeThing`, `iot:DescribeEndpoint`
(the existing account-specific Data-ATS endpoint), and the Thing's
`sparkplug` named shadow (`iot:GetThingShadow`), plus existing channel viewer
permissions: `kinesisvideo:DescribeSignalingChannel`,
`kinesisvideo:GetSignalingChannelEndpoint`, `kinesisvideo:GetIceServerConfig`,
and `kinesisvideo:ConnectAsViewer`. No channel creation or shadow update is
required. The transport vetoes the SDK's Create/Delete states.

## Runtime boundaries and tests

`core.hpp` defines the operator observations/actions and session policy.
`aws.cpp` resolves the registered type and polls the projected lifecycle every
two seconds outside the control tick. Fifteen seconds without a successful
verification shuts down. The compiled TBot profile enables MAVLink at born
REDCON 2/1 and video at 1. Unsupported types fail before connections open.

`kvs.cpp` owns independent signaling/recovery resources. `peer.cpp` owns the real
SDK peer and encoded H.264 callbacks; neither derives TBot names nor parses
MAVLink. One process-owned SDK lifetime outlives both connections. Peer recovery
backs off from one to ten seconds, with a twenty-second negotiation deadline.
Each session preserves its own error context.
If a connected MAVLink peer delivers no valid telemetry for fifteen seconds,
the runtime releases any control and retires that peer through the same bounded
recovery path. Lifecycle success and control replies do not hide telemetry
silence; healthy video keeps its independent connection. Reopening never
reacquires control automatically.

Video reaches the operator with encoded bytes, codec, SDK presentation time in
100 ns media-clock ticks, and wall-clock receipt time. Its separate consumer has
a four-frame/eight-MiB queue, drops oldest frames on overload, and rejects frames
larger than two MiB in the SDK callback. Telemetry has a separate bounded queue;
connection/control events have their own queue and take precedence. Operator
callbacks run outside SDK callbacks; a video consumer cannot block lease handling.
Callbacks must return for orderly operator-thread shutdown.

The replaceable operator uses asynchronous `acquire`, `send`, `release` and
`client_activity` actions. A queued request is not a board grant. Authority uses
`takeover=false`, exact five-second leases and returned session/epoch identity.
Sending requires a current grant. Queued frames carry that grant's local
generation and are discarded after authority loss, including after a later
explicit acquisition. Traffic submitted before a grant is rejected.
Renewal does not count as client activity. Loss, inactivity, expiry and shutdown
release authority without automatic reacquisition. Arm/disarm are uninterpreted
MAVLink traffic. Complete signed and unfamiliar MAVLink 2 frames remain byte exact.
The production observer never requests control. Tests substitute an operator
that receives both streams and sends an action through this same interface.

`just agent::test` runs lifecycle/queue/control/credential tests, real local SDK
peers with actual ICE/DTLS/SRTP/SCTP and H.264 delivery, and shadow contract checks.
The local peers exchange signaling in memory and model board lease replies;
they do not prove AWS signaling/TURN reachability or physical-board acceptance.
Record those separately using the [native acceptance record](../docs/agent-native-acceptance.md).

For an explicitly selected active Thing, the separate live acceptance executable
opens real AWS/KVS connections, then injects peer loss, lifecycle overrides and
verification failures **inside its own process**. It also suppresses telemetry
receipt while retaining the connected transport, then verifies that a fresh
peer restores telemetry without reconnecting video. It never writes a shadow,
changes the device's REDCON, acquires control, or sends a MAVLink action. It is
excluded from default CTest:

```sh
just agent::build
just agent::trust
tmp/agent-build/agent-live-tests <thing-id> eu-central-1 "$PWD/tmp/agent-trust/aws-roots.pem"
```

On the observed TBot, requesting REDCON 2 while actual REDCON is 1 succeeds
without making actual REDCON exactly 2. Capability-derived lifecycle and the
shared public 1/2/3 MCU wake command explain this behavior; Office's pending
arrow clears when the request is satisfied. The live test's override verifies
agent video-only gating and reopening with real peers, not a physical REDCON
transition. The board KVS 0.18.2 log also showed intermittent signaling-write
timeouts; agent retries recovered each stream independently.

## Local rollout

Manually install native prerequisites, configure the authorized SDK profile,
then build/test and run the observer against an existing supported active Thing.
Record the revision, dirty-source diff, dependency versions, commands and logs.
No agent deployment, component publication, board update or firmware flash is
needed for this local issue. Before later cloud replacement follow the
[manual retirement runbook](../docs/constraints/agent-rollout.md).
A future immutable agent release needs its own version and publication gates.
