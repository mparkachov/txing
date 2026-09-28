# TBot cloud companion infrastructure

`template.yaml` is the dedicated, forward-only stack for on-demand TBot cloud
companions. It creates an ECR repository, two public dual-stack subnets, an
internet gateway and public routes, UDP 14550 ingress on IPv4 and IPv6, an ECS
cluster, scoped IAM roles, and log groups. It creates no ECS service, running
task, load balancer, or fixed address. Lifecycle triggers default to disabled.

The task definition appears only after an immutable companion image digest is
provided. The Go controller Lambda appears only after both that digest and a
versioned controller bootstrap artifact are provided. This lets the first
stack deployment create the ECR repository without needing an unpublished
image. With both artifacts present, the stack also creates a completed
Sparkplug shadow-update rule and a one-minute reconciliation rule. Both stay
disabled until the operator sets `EnableLifecycle=true`.

## Manual deployment order

Use the established AWS profile and Region for the txing environment. Set
`TXING_AWS_STACK` to its stack prefix (for example `town`) and
`LAMBDA_ARTIFACT_BUCKET` to the existing runtime Lambda artifact bucket. These
commands are for the operator; repository validation does not deploy AWS
resources.

1. Deploy the network, repository, IAM, logs, and empty cluster:

   ```sh
   aws cloudformation deploy \
     --stack-name "${TXING_AWS_STACK}-tbot-companion" \
     --template-file devices/tbot/cloud/template.yaml \
     --capabilities CAPABILITY_IAM \
     --parameter-overrides \
       "EnvironmentStackName=${TXING_AWS_STACK}" \
       "LambdaArtifactsBucketName=${LAMBDA_ARTIFACT_BUCKET}"
   ```

2. After Issue #158 supplies the versioned `linux/arm64`
   `txing-tbot-companion` image, publish it to the new repository and retrieve
   its `sha256:` digest. After Issue #155 supplies the Go
   `txing-tbot-companion-lambda` controller and Issue #158 packages its
   versioned `provided.al2023` bootstrap zip, publish that zip to the Lambda
   artifact bucket. Update the same stack with
   `CompanionImageDigest=sha256:...` and the **versioned**
   `ControllerLambdaS3Key=...` in `--parameter-overrides`, alongside the two
   required parameters above. CloudFormation then registers the digest-pinned
   task definition and creates the controller Lambda. Do not use a mutable image
   tag or a `current/` Lambda key for this update.

3. Before Issue #155 enables task starts, check the effective ECS
   `dualStackIPv6` account setting for the controller role shown in the stack's
   `ControllerRoleArn` output, which will call `RunTask`.
   Enable it through the operator's normal AWS account-setting process if it is
   disabled. The controller must launch on Fargate Linux platform `1.4.0` or
   newer with both output subnet IDs, the output security group, and
   `AssignPublicIp=ENABLED`. AWS assigns a dynamic public IPv4 address and an
   IPv6 address to each task ENI. The controller publishes those addresses only
   when the UDP listener and MAVLink data channel are ready.

4. Re-enlist existing TBot Things to provision their optional `agent` shadow.
   Ensure the environment's `AWS_Things` fleet index is enabled with registry
   indexing; the controller queries `thingTypeName:tbot` and verifies each
   Thing with `DescribeThing`. Enable the shadow-update trigger and minute
   reconciliation by updating this stack with `EnableLifecycle=true` only
   after the #156/#157 runtime and #158 versioned artifacts are ready. Keep all
   four artifact/environment parameters from step 2 in this update. At rest,
   `aws ecs list-tasks --cluster
   "${TXING_AWS_STACK}-tbot-companion"` should show no running companion tasks.

The endpoint accepts UDP 14550 from any IPv4 or IPv6 source and has no
authentication. An operator must treat the displayed address as a live physical
control endpoint. TBot's `agent` shadow is the only intended Office display,
under Debug. The shared task role is limited to TBot signaling channel names,
read access to TBot `sparkplug` and `agent` named shadows, and write access to
TBot `agent` named shadows. The controller has the ECS and network read
permissions needed to reconcile tasks and publish addresses. The shared task
role can address other TBot Things, so runtime code must validate the assigned
Thing ID and use only that Thing's channels and shadows.

The CloudFormation stack does not change the cloud MCU VPC or its ECS cluster.
The ECR repository is retained if this stack is deleted; any manually required
cleanup remains an operator action.

## Controller behavior

The Go controller handles `sparkplug`, `sweep`, and internal `readiness` events.
The IoT rule listens to completed
`$aws/things/+/shadow/name/sparkplug/update/documents` messages and sends only
the Thing name. Every decision rereads the current projection; event payloads
cannot replay an old REDCON. Only TBot `DBIRTH` or `DDATA` at REDCON 1 or 2 is
active. A missing/dead projection or REDCON 3/4 clears the shadow task identity
and endpoint before requesting ECS shutdown. The minute sweep also examines
managed tasks, including those whose registry Thing disappeared or is absent
from the fleet index. Other device types and unmanaged ECS tasks are ignored.

Lambda reserved concurrency is **one**. Do not increase it: it serializes
controller decisions across execution environments. The `agent` shadow's
opaque task ID is a persisted launch token. ECS `clientToken`, `startedBy`,
task tags, and the container environment carry that same token. A lost RunTask
response is retried with the same token. Confirmed failed starts/crashes wait
until the launch is at least one minute old before replacement; provisioning
or readiness that remains stalled for ten minutes is stopped and replaced.
Superseded tasks are fenced and stopped before a new task may launch. REDCON
1↔2 retains the task; the runtime controls its independent video connection.

SDK requests allow at most three attempts and an eight-second HTTP timeout;
invocations have a 50-second work deadline. Shadow updates allow at most three
version-conflict attempts. Fleet/ECS pagination is bounded to 100 pages per
enumeration. Lambda function-error retries and EventBridge target retries are
disabled. Lambda can still queue throttled asynchronous invocations for up to
60 seconds; the next minute pass repairs failed delivery. See the
[AWS asynchronous retry semantics](https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html).
Inspect the controller CloudWatch logs for the Thing, launch token, and error,
and monitor Lambda `Errors`, `Throttles`, and `AsyncEventsDropped` plus
EventBridge `FailedInvocations`. A missing `agent` shadow reports an explicit
re-enlistment error rather than creating unfenced state.

### Runtime readiness contract (#156/#157)

Each task receives `TXING_THING_ID`, `TXING_AGENT_TASK_ID`, and
`TXING_AGENT_CONTROLLER_FUNCTION` through ECS overrides. `task.id` in the
shadow is the launch token; the ECS task ARN comes from Fargate task metadata.
The task may update connection state through the existing fenced
`agentstatus.Update` helper, but endpoint publication belongs to the controller.
For publication, read the current `agent` shadow version, take a fresh snapshot
of the listener and connections, and invoke the assigned controller Lambda
with `InvocationType=RequestResponse` and this payload:

```json
{
  "kind": "readiness",
  "thingName": "tbot-...",
  "readiness": {
    "taskId": "opaque-launch-token",
    "taskArn": "arn:aws:ecs:REGION:ACCOUNT:task/CLUSTER/TASK",
    "shadowVersion": 42,
    "udpListening": true,
    "mavlink": "connected",
    "video": "disconnected"
  }
}
```

Connection values are `disconnected`, `connecting`, `connected`, or `error`.
Send the current snapshot on listener/connection changes and every 30 seconds
while running. A Lambda transport error, `FunctionError`, pending/stopping
task, or shadow-version conflict requires a bounded retry with a freshly read
version and a newly sampled snapshot; never resend old readiness with a new
version. After three attempts, wait for the next reporting interval. A fenced
task ID requires shutdown and lease release. These calls must run independently
of MAVLink/lease processing. Lambda invocation permission is scoped to this
controller; no EC2 read permission is given to the task.

The controller checks task identity/ARN, current lifecycle, ECS running state,
and reported listener/MAVLink readiness, then obtains both addresses from that
task's ENI. It publishes only after a version-conditional write. A stale report
cannot overwrite a newer loss-of-link snapshot, and a video error does not
clear an otherwise ready MAVLink endpoint. The minute sweep clears an endpoint
that no longer matches its live task/ENI; the next fresh report can restore it.
Null fields in shadow update requests clear AWS IoT properties; readers treat
an absent nullable property as null.

## Local validation

From `devices/tbot/cloud`:

```sh
go test -race ./...
go vet ./...
go test ./companion -run '^$' -fuzz FuzzMAVLinkBoundaries -fuzztime 5s
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build \
  -trimpath -o ../../../tmp/tbot-companion-bootstrap \
  ./cmd/txing-tbot-companion-lambda
```

From the repository root:

```sh
uv run --no-project --with cfn-lint cfn-lint \
  --template devices/tbot/cloud/template.yaml --regions eu-central-1
uv run --no-project --with pyyaml python -m unittest discover \
  -s devices/tbot/cloud/tests -v
```

These checks use fake AWS endpoints and do not deploy resources. Versioned
release packaging/publishing remains in #158. After manual activation, verify
REDCON 3→2→1→2→3/4 and death on a lifted TBot, force a companion task exit,
and inspect `agent` in Office Debug for identity replacement and endpoint
cleanup. To deactivate, set `EnableLifecycle=false`; this stops triggers but
does not drain already running tasks. Manually stop those tasks, clear their
`agent` status to the stopped default, and verify the cluster is empty.

## Companion viewer runtime

`cmd/txing-tbot-companion` is the Fargate task entry point. It validates its
assigned `tbot-*` Thing and 32-hex launch token, obtains its ECS task ARN from
the injected v4 metadata endpoint, and uses only the assigned Thing's shadows
and signaling channels. AWS credentials come from the Fargate task role;
static credentials and local AWS profiles are not used by this entry point.

At REDCON 2 or 1, a native `txing-tbot-kvs-viewer` process joins
`<thing>-mavlink` as a KVS **viewer**, opens ordered/reliable
`txing.mavlink.v1`, and delivers complete binary messages plus JSON lease
messages to the Go runtime without modifying their bytes. Opening the viewer
sends no activation, renewal, or MAVLink uplink. The Go bridge binds IPv4 and
IPv6 UDP 14550 and reports actual listener readiness; both families must bind
successfully. A task becomes publishable only when that listener and the
MAVLink data channel are ready. Keep lifecycle activation disabled until #158
provides the versioned artifacts.

### QGroundControl UDP and lease behavior

The first complete MAVLink 2 datagram selects one source address and port.
Telemetry reaches that source before control. Other senders cannot transmit,
renew control, or extend its five-second inactivity deadline. A malformed or
incomplete datagram selects no source and forwards no partial result. Uplink
splits valid datagrams into complete frames; downlink requires one frame per
WebRTC message and sends one frame per UDP datagram. Signed and unfamiliar
frames retain their original bytes. Unknown incompatibility flags are rejected;
ordinary forwarding does not impose a MAVLink dialect or validate signatures.
The flight controller remains the protocol authority.

All pre-arm uplink, including parameter requests, is held back. Only a CRC-valid
`COMMAND_LONG` or `COMMAND_INT` with `MAV_CMD_COMPONENT_ARM_DISARM` and parameter
1 equal to 1 requests `control.activate` with `takeover=false`. The original arm
frame is sent only after the matching successful grant. A busy Office lease
leaves QGroundControl observing telemetry; only a fresh arm request retries
acquisition. Pre-arm frames are discarded, never buffered for later replay.

Active control forwards complete frames only from the selected sender and
renews every two seconds while it remains live. Lease responses must match
request identity, actor, session and epoch. A one-second acquisition/renewal
response timeout closes that WebRTC peer using the existing bounded reconnect
budget; closing also clears a possible unacknowledged board grant. Queued arm
traffic from before a connection opened cannot acquire its lease.

A CRC-valid disarm frame is forwarded first, then uplink is held until its
CRC-valid terminal `COMMAND_ACK` or a one-second bound, followed by release.
An acknowledgment must match the command's target and sender when those IDs
are present; in-progress or unrelated acknowledgments do not release early.
Five seconds of selected-sender inactivity releases control and frees the
source. WebRTC loss and task shutdown also release control; graceful shutdown
sends release before destroying the worker. A new arm is required after every
release. If release cannot be delivered over a lost transport, the board's peer
closure/five-second lease expiry and safe-state policy remain the final boundary.

UDP receive queues are bounded to 64 datagrams, with arrival timestamps so a
backlog cannot extend inactivity. UDP losses are not retransmitted. Each
transport send has a 250 ms bound; lease/source deadlines are checked every
50 ms and before processing messages. Connection/readiness reporting and video
supervision run independently of this control loop. Large datagrams yield
between frames so they cannot monopolize lease responses or shutdown.

For manual acceptance, add a QGroundControl UDP link to the live IPv4 address
in TBot's Office Debug `agent` shadow on port 14550. On a secured lifted TBot,
verify observer telemetry, arm, motion, disarm, five-second sender loss, WebRTC
loss, and contention while Office owns control. If QGroundControl cannot send
arm without pre-arm parameter traffic, stop and revisit the strict arm rule;
do not acquire control earlier. #159 owns this physical acceptance.

### Independent video and runtime bounds

At REDCON 1, a separate native process joins `<thing>-board-video`. It
negotiates receive-only H.264 and discards frames in the SDK callback without
decoding, forwarding, or storing them. Its connected state requires actual
frame reception. REDCON 2 closes only video. Video failures and reconnection
have their own supervisor and cannot reset the MAVLink process. The pinned SDK
advertises an SCTP media section in viewer offers even for video; the video
worker creates no data channel and sends no data-channel messages.

Runtime bounds:

- Authoritative `sparkplug` and `agent` checks every two seconds, with a
  four-second deadline per check. REDCON 3/4, death, or a fenced task identity
  stops both workers. Fifteen seconds without a successful authority check
  also stops the task.
- A viewer attempt has 45 seconds to establish its MAVLink channel or receive
  its first video frame. SDK signaling retries/reconnect are disabled; the Go
  supervisor owns attempts. Failed attempts wait one second, then two seconds,
  then a one-minute cooldown after the third failure. Thirty seconds of a
  healthy connection resets the failure budget.
- Worker IPC messages have a 64 KiB limit, receive queues hold 64 messages,
  and send queues hold 16. Overflow fails the affected session. Frames never
  become partial messages or silently truncated data. A stalled IPC writer is
  stopped within two seconds; native worker cleanup has a five-second bound.
- Total task shutdown has a ten-second deadline, including final fenced
  connection-state cleanup. Controller reconciliation independently clears
  endpoints and stops stale tasks.
- Connection changes and 30-second heartbeats update the assigned `agent`
  shadow and invoke the readiness handler. Each conflict/retry rereads the
  version and resamples the connection state; at most three fresh invocations
  are attempted. These operations run independently of message handling.

Native viewers retrieve temporary credentials directly from the task-role
provider every 30 seconds, preserving their actual expiry. AWS API clients
separately use an SDK cache with a five-minute early-refresh window. Viewer
credentials travel only in anonymous parent/child
pipes and remain in memory. Refresh updates the native credential provider
without replacing its peer. A transient credential endpoint failure retains
still-valid credentials; failure to obtain credentials valid for another
minute closes that worker. Native diagnostics expose only operation names and
status codes, suppressing credential-bearing SDK request logging.

The runtime's single TLS trust anchor defaults to
`/etc/ssl/certs/Starfield_Services_Root_Certificate_Authority_-_G2.pem` and can
be changed with `TXING_KVS_SYSTEM_CA_CERT_PATH`. Use a single trusted root
certificate, not a full OS CA bundle. The task image contains the required
anchor. `TXING_KVS_VIEWER_PATH` can select a locally built native worker;
production uses `/usr/local/bin/txing-tbot-kvs-viewer`.

### Build and validate the viewers

Both the board master and companion consume
`devices/common/kvs/cmake/AwsKvsWebRtc.cmake` and the SDK pin in
`devices/common/kvs/sdk.commit`. Builds fetch the SDK and its own pinned
producer/PIC dependencies into their build directory; source is not vendored
into the product tree. The existing board system-dependency staging behavior
is shared without changing its runtime protocol.

From the repository root, build a native development worker using installed
OpenSSL, libwebsockets, libsrtp2, libusrsctp, log4cplus, curl, zlib, CMake,
and a C++17 compiler:

```sh
cmake -S devices/tbot/cloud/viewer -B tmp/tbot-viewer-build \
  -DCMAKE_BUILD_TYPE=Release
cmake --build tmp/tbot-viewer-build --parallel 4
ctest --test-dir tmp/tbot-viewer-build --output-on-failure
```

CTest connects real pinned-SDK master/viewer peers over kernel UDP with
ICE/DTLS/SCTP/SRTP. Its test-only interface enumeration exposes localhost to
avoid dependence on LAN/VPN routing; this fixture is never linked into the
production worker. Checks cover ordered binary/JSON delivery, signed-frame
byte preservation, observer startup without uplink, temporary credential
replacement, and actual H.264 receive/discard callbacks. No AWS service or
physical device is contacted.

For the production `linux/arm64` image, use a local container engine (the
repository's usual `nerdctl`, or equivalent). Build context is the repository
root; the Dockerfile-specific ignore file excludes unrelated source and local
credentials:

```sh
nerdctl build --platform linux/arm64 \
  -f devices/tbot/cloud/Dockerfile \
  -t txing-tbot-companion:local .
```

The container build compiles the real viewer and runs the real peer tests on
Linux. Its final Alpine image runs as UID/GID 10001 and contains only the
Go runtime, native worker, runtime libraries, and trust anchors. The `local`
tag is for validation only; #158 owns versioned ECR publication and the
CloudFormation image digest. Keep AWS lifecycle rules disabled until #158
provides versioned artifacts.

After #157/#158, the operator deploys the immutable image digest and versioned
controller artifact using the manual stack sequence above, then enables the
lifecycle rules. Verify the published `agent` shadow in Office Debug and run
#159's lifted-device acceptance. This change does not require board firmware
flashing or automatic AWS deployment.
