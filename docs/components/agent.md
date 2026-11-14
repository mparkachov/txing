# Agent

The agent is the AI counterpart of Office. It receives telemetry and encoded
video and exposes authorized actions to an interchangeable operator. The
current operator forwards MAVLink to QGroundControl and counts video frames.
One C++ runtime runs on macOS and Linux ARM64 Lambda MicroVMs. TBot supports
observation and manual control. Virtual quad supports receive-only observation.
Cloud operation can start automatically when a device is ready and the operator
has enabled launches.

The current implementation provides observation and manual control. Model
inference, video decoding and autonomous motion are outside its scope.

## Runtime responsibilities

| Responsibility | Owns |
| --- | --- |
| Device session | Registered device profile, independent WebRTC connections, telemetry and video delivery, and the board control lease |
| Operator behavior | Observations and actions for the manual QGroundControl operator |
| Hosting | Local startup or MicroVM lifecycle, credentials, execution authorization, and diagnostics |

The `txing-agent` process links the pinned AWS KVS WebRTC C SDK directly. It
initializes the SDK once and shares that lifetime across both sessions.
Keep one C++ runtime for macOS and Linux ARM64 and one C++ controller. Build
and publish through CMake, Just and minimal POSIX shell. The existing Go
witness handles independent stop-only repair. [Lambda language boundary](../aws-lambda-boundary.md)

The runtime uses the AWS SDK for C++ for API calls and static or refreshable
credentials. It adapts those credentials to the KVS provider in process. The
SDK handles signaling, while the application manages device lifecycle and
bounded peer recovery. HTTP/WebSocket support uses libwebsockets.

Transport receives explicit channel, region, media/data role, and data-channel
label. It neither derives TBot names nor parses MAVLink nor manages cloud runs.
Diagnostics retain SDK errors and operation context while excluding secrets.
Native transport diagnostics sample SDK ICE packet/byte/consent counters and
adapter counts of successful SDK sends and receive callbacks every five seconds
while connected, and once before teardown. Numeric sample time and the generated
peer identity correlate with board logs. Samples omit addresses, labels, peer
payloads and authentication material.

### Operator interface

The operator receives telemetry, encoded video, connection changes, and control
loss. It can request control, send MAVLink, and release control. Video includes
codec, presentation timestamp, and local receipt time. Timestamps retain their
respective clock meanings and do not imply cross-stream synchronization.

Operator callbacks run outside the SDK callback. Video has its own bounded
queue of four frames and eight MiB. It drops the oldest frame on overload and
rejects frames larger than two MiB. Telemetry and connection/control events
have separate bounded queues. The manual operator counts and discards video
at the operator boundary, and the test operator consumes both streams and
issues an authorized action through the same interface.

### Profiles and lifecycle

The agent resolves the registered AWS IoT Thing type before opening sessions.
Its compiled TBot profile uses the channel templates and activation rules in
the device manifest.

- `<thing-id>-mavlink`: ordered reliable data channel `txing.mavlink.v1`,
  active at born REDCON 2 or 1.
- `<thing-id>-board-video`: receive-only video, active at born REDCON 1.
- REDCON 3/4, device death, or expired execution authorization initiates shutdown.

The virtual-quad profile receives the same two channels through KVS TURN. It opens them at
operational REDCON 1 once the Sparkplug projection matches the current simulation
session ID and readiness watermark. Readiness loss, readiness expiry or a new
simulation session closes both peers. The native command and cloud attachment
reject `--control` for virtual quad, and the cloud runtime rejects lease and
MAVLink sends from an attached observer. The simulator owns flight readiness and
session deadlines. [Virtual quadcopter architecture](../virtual-quadcopter-architecture.md#agent-observation)

Unsupported registered types fail before session creation. A name prefix alone
does not establish support. Rig and witness remain lifecycle authorities.

The agent polls lifecycle every two seconds and stops after fifteen seconds
without authoritative verification. Video and MAVLink recover independently.
Returning from REDCON 1 to 2 closes only video. Fifteen seconds without a valid
MAVLink telemetry frame triggers bounded peer recovery. The runtime measures
receipt per peer generation, releases authority and fences queued sends before
retiring the peer. Healthy video continues and control requires a fresh request.

### Control authority

Follow the [board MAVLink contract](../contracts/board-mavlink.md).
Observation is the default. Explicit manual control requests a free lease with
`takeover=false`. A busy owner keeps its lease. After grant, the operator
can forward the full MAVLink protocol, including pre-arm parameter traffic.

The operator session keeps the lease across arm and disarm. The agent releases
on client inactivity, disconnect, WebRTC loss, lease loss, lifecycle shutdown
or process exit. It attempts graceful release when the connection is usable.
If the link is lost, the board's five-second lease expires. A fresh explicit
request is required for another grant.

The agent validates framing and forwards complete MAVLink 2 frames byte for
byte, including signatures and unfamiliar message types.

## Native operation

### Prerequisites

On macOS install the Xcode command line tools, Just, Git, CMake, curl and these
Homebrew formulas manually:

```sh
brew install cmake just openssl@3 libwebsockets srtp libusrsctp log4cplus
```

Linux ARM64 builds use the same application source and require C/C++17 compilers,
CMake 3.24+, Git, curl, OpenSSL, zlib, libcurl, libwebsockets, libsrtp2,
libusrsctp, log4cplus, and their development headers. The production Linux ARM64 artifact is built through the release workflow below.

```sh
just agent::build
just agent::test
just agent::run <registered-tbot-thing-id> --region eu-central-1
```

The foreground run observes and logs. Ctrl-C or SIGTERM releases authority and
closes both sessions. The agent binds `127.0.0.1:14551` and sends telemetry to
QGroundControl at `127.0.0.1:14550` immediately, even before QGC sends anything.

### Local QGroundControl

In QGroundControl **Application Settings → Comm Links**, use one UDP link with
local/listening port **14550** and remote host **127.0.0.1:14551**. If configuring
that link manually, disable the duplicate UDP auto-connect link. Keep heartbeat
emission enabled under Telemetry/MAVLink settings. [QGC Comm Links](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/comm_links.html) ·
[QGC Telemetry settings](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/telemetry.html)

```sh
# View telemetry without control.
just agent::run <registered-tbot-thing-id> --region eu-central-1

# Explicit full MAVLink control, including parameter retrieval/configuration.
just agent::run <registered-tbot-thing-id> --control --region eu-central-1

# Different agent listener; change QGC's remote host to 127.0.0.1:15551.
just agent::run <registered-tbot-thing-id> 15551 --control --region eu-central-1

# Different QGC listening port as well; configure its local port to 15550.
just agent::run <registered-tbot-thing-id> 15551 --qgc-port 15550 --region eu-central-1
```

The configured loopback QGC source port establishes presence and sends uplink.
Initial valid MAVLink 1 heartbeats establish presence locally. The board channel
uses MAVLink 2, and telemetry initiates QGC negotiation. Each UDP datagram must
contain complete frames. The flight controller validates MAVLink 2 CRCs and
signatures.

`--control` makes one `takeover=false` lease attempt after client presence and
telemetry readiness. The agent drops pre-grant traffic, and QGC can retry
after the grant. A busy Office or other peer remains owner. Once granted,
parameter/configuration, arm, disarm and re-arm traffic use that same lease.
Video counters are logged by the operator and QGC displays telemetry.

Control releases after five seconds without valid client traffic, local socket
failure, WebRTC/lease loss, lifecycle shutdown, or process exit. The same
five-second deadline detects link disconnection or QGC exit. Only valid uplink
traffic counts as client activity. Restart with `--control` after a busy, lost
or released attempt.

Ports must be distinct integers from 1 to 65535. If the agent listener is
occupied, stop its other owner or choose another positional port. Diagnostics
include individual connection errors, control changes, observation counts,
rejected datagrams and dropped UDP/enqueue sends. Work is bounded to 32
datagrams per poll, with limits of 16 KiB and 32 complete frames per datagram.
The agent rejects malformed, truncated and excessive datagrams in full.

The native command uses the existing board services and AWS IoT/KVS resources.
End foreground sessions by the [fifty-minute ceiling](#session-duration).

### Build cache

Native builds cache objects and SDK sources under `tmp/agent-build/`. CMake
pins the AWS SDK for C++ and reads the shared KVS pin from
`devices/common/kvs/sdk.commit`. The agent applies its libwebsockets event-loop
patch to its own SDK checkout. `TXING_AGENT_BUILD_JOBS` defaults to four.
Pass options with `just agent::build <cmake-options>` and rebuild the cache
after changing the native toolchain or dependency prefix.

### Credentials and TLS

The application uses the AWS SDK for C++ default provider chain for both IoT
and KVS signing. Use `AWS_PROFILE` to select a configured local profile, and
`AWS_CONFIG_FILE` / `AWS_SHARED_CREDENTIALS_FILE` for explicit file locations.
Static profiles and environment credentials (`AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`) work. Temporary credentials also require
`AWS_SESSION_TOKEN`. Manually exported temporary credentials expire.
Use a refreshable SDK provider (profile role/process, SSO with its existing login,
web identity, or execution-role/container credentials) for long runs. Authenticate
that provider before startup. Expired or missing credentials cause
errors and lifecycle expiry.

The default SDK region/profile configuration is used unless `--region` overrides
it. The adapter consults the provider again when KVS requests signing
credentials and preserves expiration and session tokens.
Tests isolate their SDK profiles in repository `tmp/agent-test/`.
See the [AWS credential-provider documentation](https://docs.aws.amazon.com/sdk-for-cpp/v1/developer-guide/credproviders.html).

`run` downloads the five public AWS trust roots from the
[Amazon Trust Services repository](https://www.amazontrust.com/repository/),
verifies their published SHA-256 DER hashes and expiry on every invocation, and
assembles `tmp/agent-trust/aws-roots.pem`. It never disables TLS verification.
For a direct binary invocation, run `just agent::trust` and provide its
result via `--ca` or `TXING_AGENT_CA_PATH`. Investigate a failed verification
with TLS verification enabled. SDK credential providers may also need their normal host trust
store for external identity-provider endpoints.

The identity needs read access to `iot:DescribeThing`, `iot:DescribeEndpoint`
(the existing account-specific Data-ATS endpoint), and the Thing's
`sparkplug` named shadow (`iot:GetThingShadow`), plus existing channel viewer
permissions including `kinesisvideo:DescribeSignalingChannel`,
`kinesisvideo:GetSignalingChannelEndpoint`, `kinesisvideo:GetIceServerConfig`,
and `kinesisvideo:ConnectAsViewer`. A native run uses those device resources
directly. It runs without the agent stack, logs status locally and leaves the
controller-owned `agent` shadow alone. The transport vetoes the SDK's
Create/Delete states.

## Cloud operation

The cloud runtime runs in Lambda MicroVMs in `eu-central-1`. Attachment uses
authenticated HTTPS/WebSocket ingress. The run hook initializes unique
device/run identity, execution-role credentials and WebRTC after snapshot
restoration. Keep live sessions and credentials out of the snapshot. Automatic
idle suspension and resumption are disabled so an active device can be
observed before anyone attaches. The stack uses managed public networking.
Drain inactive devices to zero running VMs and keep legacy ECS, ECR and
dedicated VPC/NAT infrastructure out of the agent stack.

### Session duration

`ActivationBudgetSeconds` defaults to 3000 and accepts 1–3000 seconds.
The controller persists the absolute deadline for each activation, and
replacement VMs receive only the remaining budget. A shorter setting applies
to new activations. Retries, publication and configuration updates preserve
existing activation IDs and deadlines. At expiry the agent releases control
and stops. A new TBot activation requires a verified inactive-to-active
transition. A virtual-quad activation uses the simulator's session ID and ends
by the earlier of the simulator's flight deadline and the configured agent
budget. A replacement observer for that session retains the original cutoff.

Native sessions have the same fifty-minute operating ceiling and the operator
ends them manually. Disposable MicroVM requests use a 3000-second hosting
cap. TBot's board renews its IoT credentials about every fifty-five minutes
and replaces the KVS sessions during renewal. MAVLink readiness can drop and
cause REDCON 3 and agent shutdown. An already-running board can reach renewal
before the agent deadline. Track the renewal issue separately. [Board credential renewal](https://github.com/mparkachov/txing/issues/174)

### Controller and authorization

A small C++ controller Lambda responds to completed projected lifecycle changes
and a one-minute repair pass. It verifies current registered type/lifecycle,
starts at most one authorized agent per supported active device, and terminates
inactive, failed, or superseded runs. Launches are idempotent and retries are
bounded. Repair handles missed events, interrupted launches, and orphaned runs.

For TBot, the controller requires an inactive observation before the first activation.
When it misses an inactive interval, it retains the expired activation until
it directly observes another verified inactive-to-active transition. It
measures the budget from the last verified inactive observation, which can
shorten the available time. The [agent shadow contract](../contracts/agent-shadow.md)
defines ordering, missing projections and assignment fencing.

The cloud runtime verifies its assignment in addition to device lifecycle.
Stale assignments cannot retain control or advertise a usable attachment.
Connection recovery belongs to the runtime: a temporary video/MAVLink
interruption does not justify replacing a healthy MicroVM.

The controller is the sole operational writer of the `agent` named shadow.
It records run identity, release, lifecycle/deadline, HTTPS endpoint and
sampled status. Use the run identity and freshness when interpreting the
runtime's connection, video, control and error samples. [Agent shadow contract](../contracts/agent-shadow.md)

The [witness shutdown watch](witness.md#agent-shutdown-watch) provides
independent delayed shutdown repair. It retains healthy assignments and checks
off/expired runs and aged unassigned instances of the dedicated image. It has
its own minute schedule and never writes agent shadows or launches agents.

TBot declares `agent` in the capability catalog. The rig publishes
`capability.agent=true` at born REDCON 1/2 and false when inactive. The virtual
quad controller publishes it only for an operational simulator with fresh
MAVLink and video readiness. Execution requires the registry declaration and
verified availability. Removing the declaration or reporting false revokes
authorization. Office shows the agent shadow in Debug for devices declaring
the capability. The simulator controls its own readiness and flight authority.

### Cloud attachment

With cloud launches enabled and a verified current assignment, use the same
QGroundControl link configuration as a local run.

```sh
just agent::attach <registered-tbot-thing-id>
just agent::attach <registered-tbot-thing-id> 14551 --control
```

Attachment discovers and verifies the current assignment, obtains a token for
port 8081, and forwards through the existing agent's device session.
Observation is the default. `--control` makes one free-lease
attempt after QGroundControl presence and telemetry readiness. Only one manual
attachment is accepted. Inactivity, connection loss, assignment loss, token
cutoff or process exit releases manual control without reacquisition. The
client requests a five-minute token and closes at four minutes. Start another
explicit attachment to continue. While connected, it periodically checks the
token with an authenticated status request and closes if that check fails.
The cloud agent observes telemetry and video before any attachment.

## Deployment

CloudFormation deployment and publication are operator actions. Use the
established environment prefix, AWS profile and Frankfurt region. Keep
`AutomationEnabled` and `PrerequisitesConfirmed` false while preparing
infrastructure, replacing image identity or validating a storage reset.

### Agent capability rollout

Deploy the shared catalog with `just aws::deploy`. Re-enlist existing TBot
devices with `just aws::deploy-device <rig-thing-id> tbot <registry-name>`.
The registry name is the Thing's original `attributes.name`. Verify the
existing Thing ID is retained, `created=false` and `agent` is declared.
Re-enlistment initializes a missing shadow and preserves existing payloads.

The installed rig runtime must publish `capability.agent` from the device's
actual lifecycle state. Use the normal rig release and installation process for
changes. Office is published from Git and reads the capability and shadow for
Agent Debug. Deploy witness with the same dedicated image name to enable its
independent schedule. [Witness deployment](witness.md#deploy)

### Initial deployment

For an environment with legacy Go/Fargate companion resources, first follow
[legacy retirement](#legacy-retirement). Then download the selected immutable
GitHub release and verify its checksums and metadata. Upload `controller.zip`
to an existing bootstrap bucket under an immutable key with conditional S3
PutObject (`--if-none-match '*'`). From the repository root, set the
reviewed bucket/key and run the operator deployment.

```sh
export TXING_AGENT_CONTROLLER_BUCKET='<existing-bootstrap-bucket>'
export TXING_AGENT_CONTROLLER_KEY='agent/<version>/controller.zip'
just agent::deploy
```

The recipe checks regional Lambda concurrency headroom and creates a new stack
with both launch gates false. The stack creates the unversioned release bucket,
build and execution roles, logs, controller, and a managed policy for operator
attachment. The controller reserves concurrency one to serialize reconciliation.
If initial creation rolls back to `ROLLBACK_COMPLETE`, inventory resources and
delete the failed stack manually before retrying. Review retained buckets
separately and preserve the bucket containing the bootstrap controller.

Grant the attachment policy only to trusted operator principals. Token creation
is scoped to the dedicated image, so the caller must choose the attachment
port. Keep tokens for internal hook ports private.

### Enable and drain

Publish a verified release and check the controller digest, image/version,
rig-projected availability and witness watch before enablement. The operator
sets `PrerequisitesConfirmed=true` and `AutomationEnabled=true` on the
existing stack when the environment is approved for cloud operation. Verify
an inactive controller observation before activating a device. Keep the
dedicated image name consistent between agent and witness.

For a controlled drain, secure and lift the TBot, disarm, release control and
disconnect the owning client. Set `AutomationEnabled=false` and confirm the
lifecycle trigger is disabled. The controller's one-minute EventBridge Scheduler
pass continues to terminate runs for the configured image. Witness keeps its
independent schedule. Inspect all image versions and confirm each VM is
terminal before changing image identity, retiring resources or replacing
storage. If automatic drain fails, the operator terminates the identified
nonterminal VMs and rechecks the complete inventory. Preserve the agent shadow
and its activation history during the drain.

### Legacy retirement

Only environments still running the removed Go/Fargate companion need this
procedure. Inventory the former dedicated `<environment>-tbot-companion`
stack and actual resource names, task inventory, dependency references and
retention policies.

1. Disable the old Sparkplug IoT and EventBridge minute rules. Confirm the
   old controller cannot restart tasks, including through queued retries.
2. Disarm and release on the secured device. Disconnect clients and stop old
   ECS tasks. Verify zero pending/running tasks and removal of their task ENIs.
   Retire the old controller and invocation permissions.
3. Remove the dedicated companion stack and review its retained ECR images,
   logs, release assets and companion-only `/txing/stack/TBotCompanion*` SSM
   parameters. Preserve shared Lambda artifacts, device Things and credentials,
   signaling channels and the separate cloud MCU stack and networking.
4. Once all old shadow writers are stopped, archive and delete only the old
   `agent` named shadow. Re-enlist to create the current stopped default and
   verify the schema and absent endpoint. A merge into the old shadow would
   retain old ECS task/IP/UDP fields.

## Immutable releases

An `agent-vX.Y.Z` GitHub Release contains
`txing-agent-release-linux-arm64.zip`. The archive holds `microvm.zip`,
`controller.zip`, `provenance.zip`, the hooks and initial CloudFormation
template, `release.json` and `SHA256SUMS`. The same component version covers
the runtime and controller, independently of the shared Go `lambda` stream.

`microvm.zip` contains a Dockerfile and the **prebuilt** ARM64 application and
native libraries. AWS copies those bytes and validates linking and startup.
The container base is
pinned by digest. Snapshot-safe OpenSSL is packaged with the application, and
the controller includes its non-glibc dependencies for `provided.al2023`.
Packaging checks glibc compatibility in the exact runtime and tests controller
startup in a recorded digest of `provided.al2023`.

The provenance archive records source revision and file hashes, dependency
pins, RPM inventories, ARM64 ELF checks, linker/startup checks, CTest results,
and the historical local physical acceptance record. The container digest
and the AWS managed MicroVM base version are independent build inputs.

### Build a release

Review changes and manually commit/push before creating a production release.
No recipe commits, pushes, bumps versions, flashes hardware, or publishes to
AWS as part of an artifact build. Bump `release/versions/agent` for changed
artifacts, including dependency or base-image rebuilds.

```sh
just release::bump agent <new-version>
# Review, commit and push manually, then dispatch the chosen branch.
just release::build agent <branch>
```

GitHub requires `.github/workflows/release-agent.yml` on the default branch
for `workflow_dispatch`, including dispatches that select another branch.
[GitHub manual workflow requirements](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

The manual GitHub workflow uses native ARM64 and the same
`just agent::release-package` recipe as local validation. CI explicitly selects
Docker. Workstation builds use `nerdctl.lima` with the existing engine.
The workflow checks the component's version/tag and creates one immutable
GitHub archive. The operator publishes that archive separately.

To validate packaging locally, use the existing Lima engine.

```sh
nerdctl.lima info
just agent::release-package
```

Retain the printed SHA-256, work directory and its build/packaged-runtime logs.
Packaging runs twice over a frozen tested build and requires identical archive
bytes, with normalized order/timestamps and no host UID/GID ZIP fields. The
exact packaged image is then built and run with networking disabled and no
credentials. The help command and pre-snapshot ready hook must pass. RPM
inventories capture inputs for future builds. A dirty tree produces a
validation candidate under `tmp/agent-releases/candidates/` marked
`clean=false`. Publication requires clean provenance.

### Publish a release

Use one publisher per environment at a time. Authenticate the AWS CLI and `gh`
as the operator, with no credentials in the package. The root project AWS
environment selects the established profile and stack. Publication uses
`eu-central-1`. Review the available managed base versions before publishing.

```sh
aws lambda-microvms list-managed-microvm-image-versions --region eu-central-1 \
  --image-identifier arn:aws:lambda:eu-central-1:aws:microvm-image:al2023-1
export TXING_AGENT_BASE_IMAGE_VERSION='<reviewed-AVAILABLE-imageVersion>'
just agent::publish <version>
```

The discovered artifact bucket must have **never** had versioning enabled.
The publisher checks `GetBucketVersioning` before uploading and refuses both
`Enabled` and `Suspended`. Immutable release-specific keys and conditional
writes provide the required normal-publisher immutability without S3 object
versions. Existing versioned environments require a fresh bucket. [Bucket migration](#migrate-a-versioned-artifact-bucket)

The command downloads the exact GitHub release, checks hashes and clean source
provenance, and conditionally uploads `agent/<version>/` objects to the stack's
artifact bucket. Existing objects must match byte for byte. It persists the
exact build input and derives its idempotency token from that input. Changing
the managed base or any other input at an existing version is rejected.
AWS's managed catalog can list base `2` while successful image metadata reports
`2.0`. Verification compares those equivalent forms without rewriting the
original request or its retry token. A different minor version is rejected.

The first publication creates the dedicated image named after the agent stack.
Later publications update that image. The build uses explicit ARM64,
4-GiB baseline, snapshot hooks and Internet egress, with no device identity or
live sessions in the snapshot. The dedicated image name scopes controller and
witness inventory and permissions.

Publication waits up to an hour for the **returned version** to be
`SUCCESSFUL`/`ACTIVE`, verifies artifact/base identity and the parent image's
runnable state, then writes an immutable successful-build receipt. Failed,
inactive, uncertain or timed-out builds do not change selected stack parameters.
A failed image update can still make the service's parent image unavailable
for subsequent launches. Inspect the image state and publish a new version
with the repair.

Only after success does CloudFormation select the version and matching
controller object using the existing template. All other parameters, including
`AutomationEnabled` and `PrerequisitesConfirmed`, retain their previous values.
Publication detects an intervening stack change and stops for a retry. The
command waits for the stack update and compares deployed controller CodeSha256
with the exact release ZIP. The retained work directory contains inputs,
responses, selected parameters and artifact identities. It creates no device
activation, token, attachment or VM and never changes agent shadows.

#### Retention

After verified selection, the same publication command inventories the dedicated
image and keeps the **two newest successful builds by AWS creation timestamp**,
normalized across time zones. The first publication keeps one and later
publications keep two successful builds. Retention
stops on pending/incomplete/foreign inventory, missing retained bundle objects
or a selected image outside that pair. A changed selection aborts cleanup.

The publisher deletes older successful or failed versions and confirms each
version `DELETED` or absent before deleting their source objects. It then removes
unretained `agent/<MAJOR.MINOR.PATCH>/` bundles, including partial/failed uploads
and leftovers from interrupted cleanup. Each retained bundle includes
`microvm.zip`, `controller.zip`, `provenance.zip`, `hooks.json`, `stack.yaml`,
`release.json`, `SHA256SUMS`, `build-input.json` and `built.json`. Unrelated keys
and other images are outside cleanup. S3 requests contain up to 1000 keys
and per-key deletion errors cause failure. Inventories, the retention plan and
deletion responses remain in the printed evidence directory.

Build or selection failure does not start retention. After selection, a cleanup
error exits nonzero with **“Release selected, but retention is incomplete”**.
The selection is usable. Rerun the same `just agent::publish <version>` with
the same managed base. The immutable receipt avoids another build, and current
inventories resume deletion even if an old image or some objects are already
gone. Deletion waits are bounded to five minutes per image version. A transient
error can require a later retry.

At this stage devices are assumed to run only the currently selected image
when publication starts. Keeping that predecessor alongside the new image
preserves those runs. If you need to retire a version in use, drain it before
publishing. GitHub preserves the immutable release archives outside the AWS
retention window.

#### Retry

An interrupted publication can be rerun with the same version/base: matching
objects are retained and a successful receipt avoids another build. If the
receipt is missing, the publisher first inventories the dedicated image's
versions and finds one matching every saved request setting, including base,
artifact, build role, hooks, memory, CPU and networking. It also rejects
unrequested environment variables or elevated OS capabilities. One exact match
is polled and revalidated without resubmitting an image-build request. Multiple
matches, conflicting settings for the same artifact, or unreadable inventory
stop selection. See [AWS version inventory](https://docs.aws.amazon.com/cli/latest/reference/lambda-microvms/list-microvm-image-versions.html).

Only when no version exists for that artifact does the publisher submit a
build, retaining the original request token. A missing image is accepted only
on initial creation. After an ambiguous API result, retain the evidence and
retry the same version and base. Use a new agent version to repair failed
source or configuration. A later successful publication may retire the failed
image and S3 bundle.

Existing running agents keep their stored release, exact launch request and
activation deadline. New launches use the selected release. Publication does
not drain, restart, extend an activation or enable launches. For immediate
adoption, follow [the drain procedure](#enable-and-drain) before publication,
then restore the approved launch gates and observe inactive then active.

### Migrate a versioned artifact bucket

Use this one-time procedure only for an existing versioned or suspended
artifact bucket. S3 requires a new bucket for storage with versioning never
enabled. Keep both launch gates false and confirm all VMs terminal using
[the drain procedure](#enable-and-drain).

1. Save the current stack template, parameters, resources, controller
   bucket/key and digest, image ARN, activation history and schedule state.
   Build the new immutable GitHub release before modifying AWS storage.
2. Update the existing stack with the reviewed `agent/stack.yaml`. Set
   `ImageName=disabled`, `ImageVersion=''` and `Release=''`. Preserve the old
   controller object and other parameters. CloudFormation creates
   `ReleaseArtifacts` and retains the former `Artifacts` bucket. The controller
   repair schedule pauses with no configured image. Witness keeps running.
3. After confirming terminal VMs, delete the old dedicated image and wait for
   `DELETED` or a confirmed `ResourceNotFoundException`. Keep the old bucket
   until the controller has switched. Keep the dedicated image name the same
   when recreating it so watch permissions still match.
4. Verify that the new bucket has no versioning status and publish the selected
   GitHub release. The first publication recreates the dedicated image and
   restores its controller schedule. Verify the controller bucket/key and
   digest, selected image, retained bundles, launch gates, activation budget
   and history. Start fresh from the GitHub release archives.
5. Once no stack, controller or image references the retired bucket, use the
   S3 console **Empty** action to remove every object version and delete
   marker. Confirm there are no versions, markers or incomplete multipart
   uploads. Delete only that retired bucket.

```sh
aws s3api get-bucket-versioning --region eu-central-1 --bucket "$new_bucket" \
  --query '{Status: Status}' --output json
aws lambda-microvms list-microvm-image-versions --region eu-central-1 \
  --image-identifier "$image_arn" --page-size 50 --output json
aws s3api list-objects-v2 --region eu-central-1 --bucket "$new_bucket" \
  --prefix agent/ --output json
aws s3api list-object-versions --region eu-central-1 --bucket "$old_bucket" --output json
aws s3api list-multipart-uploads --region eu-central-1 --bucket "$old_bucket"
```

The projected versioning status must be `null`. Check the full retired-bucket
inventory before deleting it. [S3 versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html) ·
[Emptying an S3 bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/empty-bucket.html)

### Permissions, base images and costs

The publishing principal needs these permissions.

- Read GitHub releases and describe or update the existing CloudFormation
  stack using its template.
- Read and conditionally upload objects in the discovered S3 bucket.
- Create, update, get and list image versions and list managed base versions.
- Read the controller configuration and pass the stack build role and managed
  Internet egress connector.

Initial deployment also needs permissions for the stack's S3, IAM, logs, IoT,
Scheduler and Lambda resources. Resolve generated role ARNs from stack
outputs. Image builds use the build role and device sessions use the execution
role. Attachment permission is granted separately to trusted operators.

Retention additionally requires `s3:GetBucketVersioning`, `s3:ListBucket` and
`s3:DeleteObject` on the discovered artifact bucket and
`lambda:DeleteMicrovmImageVersion` on the dedicated image. Do not add publisher
permissions to controller, witness or device execution roles. The one-time
manual reset separately needs whole-image deletion, CloudFormation update,
old-bucket object-version deletion and bucket deletion permissions.

Monitor managed-base availability and AWS notifications. Rebuild and publish a
new component version on a supported managed base before expiry. Update and
validate the pinned container base and packaged RPM/native dependencies for
security fixes. [AWS image lifecycle and patching](https://docs.aws.amazon.com/lambda/latest/dg/microvms-images.html)

Retained buckets, MicroVM images and snapshots, builds, CloudWatch logs,
controller/watch calls, event delivery, traffic and attachment/API usage can
remain billable at zero running agents. Logs have 14-day stack retention.
Retired versioned buckets incur storage costs until emptied. Inactive image
versions retain snapshots until deletion. Minimum storage billing and service
deletion latency can outlast publication.

## Validation and known limitations

Run `just agent::test` for lifecycle, queue, control, credential, local SDK peer
and shadow contract checks. Run `just agent::release-package` for native Linux
ARM64 packaging and startup validation. The commands exercise different layers
from a real device, AWS signaling/TURN and production lifecycle.

The separate native live test uses AWS/KVS observation on an active TBot and
injects peer loss, lifecycle overrides and verification failures inside its
own process. It sends no control actions and writes no shadows.

```sh
just agent::build
just agent::trust
tmp/agent-build/agent-live-tests <thing-id> eu-central-1 "$PWD/tmp/agent-trust/aws-roots.pem"
```

Validate a new hosting path with an operator-run disposable MicroVM before
enabling automation. Verify both device streams, role credentials, authenticated
attachment, ICE/TURN and more than fifteen minutes of observation.
`just agent::probe-package` prepares the probe. `just agent::cloud-package`
prepares the production source image context.
`just agent::controller-package` builds a local ARM64 controller candidate
using Lima. Use the immutable release workflow for deployed production
artifacts.

For manual regression checks, record the tested release, device and QGC
settings. Secure and lift the TBot before motion. Check telemetry and video,
parameter retrieval under explicit control, arm/drive/disarm/re-arm, Office
contention, and release on client, attachment or transport loss. Verify
observation at actual REDCON 1/2, shutdown on inactivity/death, and no automatic
control reacquisition. Validate local QGC operation on secured hardware before
production rollout of changes to that path. Repeat the physical checks through
cloud attachment for changes to cloud control. Verify startup before attachment,
the persisted activation budget across replacements, expiry without rollover,
and a terminal VM inventory. To test expiry sooner, set a shorter budget
while inactive, then restore 3000 after the check. Use the [witness check](witness.md#verify-shutdown-repair)
for independent shutdown repair.

The acceptance records summarize the observed results and their limits.
[Native physical acceptance](../history/acceptance/agent-physical-acceptance.md) ·
[Cloud acceptance and retention](../history/acceptance/agent-cloud.md)

Known limits include intermittent MAVLink/control stalls, camera cleanup hangs
after capture loss, and board credential renewal interrupting device sessions.
Each has its own follow-up. [MAVLink/control stalls](https://github.com/mparkachov/txing/issues/172) ·
[Camera recovery](https://github.com/mparkachov/txing/issues/173) ·
[Board renewal](https://github.com/mparkachov/txing/issues/174)

## References

- [Agent shadow contract](../contracts/agent-shadow.md)
- [Board MAVLink contract](../contracts/board-mavlink.md)
- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [TBot manifest](../../devices/tbot/manifest.toml)
- [Lambda language boundary](../aws-lambda-boundary.md)
