# Initial agent replacement and manual retirement

Status: operator runbook for the C++ replacement. Repository cleanup does not
imply deployed AWS cleanup. The #168 implementation, ARM64 artifacts and bounded
operator-run source-build test are recorded in the
[cloud evidence](../agent-cloud-build-validation.md). Launches are disabled
after that test. Immutable release publication remains #169.

Follow the [agent design](../components/agent.md) validation gates before enabling
the replacement. Native operation, the disposable MicroVM feasibility probe,
local physical acceptance, production publication, and released-cloud acceptance
remain separate gates. Prepared commands and mocks do not satisfy live evidence.

## Inventory before changing AWS

The operator uses the established profile and region to inspect the actual
environment. The historical dedicated stack was
`${TXING_AWS_STACK}-tbot-companion`; confirm its stack ID, outputs, resource IDs,
and dependencies rather than assuming a fixed IAM physical name. Useful
read-only commands, to run manually from the repository root, are:

```sh
: "${TXING_AWS_STACK:?set the existing environment stack prefix}"
aws cloudformation describe-stacks --stack-name "${TXING_AWS_STACK}-tbot-companion"
aws cloudformation list-stack-resources --stack-name "${TXING_AWS_STACK}-tbot-companion"
```

Record discovered IDs, enabled state, deployed versions, retained-resource
policies, and tasks before retirement. If the stack was never deployed, record
that evidence and skip its resource cleanup. Historical source remains in Git
history for inspection; do not restore or redeploy the removed template.

## Operator retirement order

1. Disable both old activation sources: the completed Sparkplug IoT rule
   (`CompanionSparkplugRule`, historically `<environment_with_underscores>_tbot_companion_sparkplug`)
   and EventBridge minute rule (`CompanionMinuteRule`, historically
   `${TXING_AWS_STACK}-tbot-companion-minute`). Inspect queued asynchronous
   invocations/retries and ensure the old controller cannot restart tasks.
   Disabling triggers alone does not stop running tasks.
2. On a secured, lifted TBot, disarm through the owning client, release control,
   disconnect manual clients, and verify board safe state. Drain/stop every old
   companion task, including stale/orphaned launches; verify the discovered ECS
   cluster has zero pending and running tasks and its task ENIs have gone.
   Retire the old controller and its invoke permissions so no old writer remains.
3. Remove only the obsolete dedicated companion stack/resources using the
   operator's normal CloudFormation process. Inventory includes task definitions,
   cluster, controller Lambda/async configuration, IoT/EventBridge triggers and
   invoke permissions, task execution/runtime/controller roles and policies,
   public dual-stack subnets/routes, internet gateway, security group, and VPC.
   Remove the companion-only `/txing/stack/TBotCompanion*` SSM parameters.
   Resolve dependencies manually; add no cleanup custom resource or migration
   automation. Retain logs/evidence according to the operator's retention policy.
4. Review retained ECR repository/images (`CompanionRepository` used retention),
   old `txing-tbot-companion` container images, native `txing-tbot-kvs-viewer`
   binaries, and versioned `txing-tbot-companion-lambda` bootstrap/S3 or release
   assets. Remove obsolete companion artifacts manually when no deployment
   references them. Preserve shared runtime Lambda artifacts and board/rig/KVS
   releases. Current release tooling/workflows no longer publish companion assets;
   the new agent release stream is implemented in a later issue.
5. After all old writers are stopped, archive the capability-owned `agent` shadow for
   evidence, delete only that named shadow, and initialize from
   `devices/tbot/aws/default-agent-shadow.json` (or re-enlist to create it missing).
   A merge of the new default cannot remove old `task`/IP/UDP fields: null at a
   different path does not clear them. Confirm the stopped shadow validates
   against the replacement schema and exposes no endpoint. Existing-shadow
   re-enlistment intentionally preserves the old payload and cannot perform this
   reset. Do not reset Sparkplug, MAVLink, video, board, or other device shadows.

## Preservation and replacement rollout

Do not modify cloud-MCU networking, its ECS runtime, or its stack. Do not delete
device Things/certificates, existing KVS signaling channels, board lease/epoch
protocols, or shared SDK pin/build resources. Board, rig, and Office connection
fixes remain independent of retiring the old agent.

Deploy updated shared AWS catalog/enlistment code through the normal operator
`just aws::deploy` flow when new-default provisioning is needed. Admin Lambdas
are content-addressed; no shared runtime `lambda` or board release is needed
for this cleanup. Office discovers agent diagnostics through declared capabilities. No firmware flash or device binary update is required by #163.

The later replacement deployment uses managed public networking, S3, IAM, logs,
the C++ controller, and lifecycle triggers. Enable it only after its preceding
native/probe/physical gates and initial retirement are recorded. At most one
current authorized run may exist per device, with a persisted activation deadline
of at most fifty minutes shared across its replacements, under the
[current-stage duration decision](agent-session-limit.md). New disposable
requests use a 3000-second hosting cap; planned controller replacements use only
the remaining activation budget. Acceptance must exercise that boundary before
released-cloud operation. Board credential-renewal repair remains deferred.
Ordinary immutable publication affects later launches; it leaves existing runs
on their current version. Immediate adoption requires manual disarm, release,
and drain. Bump the new `agent` component version before producing a new release
artifact once its publication workflow exists.

Record operator identity/time, source revision and versions, old trigger states,
zero old tasks, shadow reset, exact retired/retained resources, acceptance logs,
and zero running replacement MicroVMs after inactivity. These instructions do
not authorize agents to execute AWS mutations, cleanup, commits, or flashing.

## Agent capability rollout

`agent` is a declared capability, with a normal capability-owned named shadow.
The 2026-10-29 operator correction supersedes the earlier optional-shadow
exception. Apply the catalog/admin update with `just aws::deploy`, then re-enlist
existing supported devices using their original registry name (`attributes.name`),
not their Thing ID. For the current device:

```sh
just aws::deploy-device raspi-6q6abe tbot tbot
```

Its result must retain `tbot-8yzfgj`, report `created=false`, and include `agent`
in the capability attribute. Existing shadow payloads are preserved. Device types
without the capability do not provision it or authorize an agent.

Before publishing changed runtime artifacts, bump the `rig` and shared `lambda`
versions above their published versions. Install the new rig runtime through the
normal manual release process: it publishes `capability.agent` for eligible
REDCON 1/2 devices. Deploy the updated Office through its Git-driven flow, and
rebuild the controller and production MicroVM image from the changed sources.
The older locally validated artifacts predate this capability correction.
Keep automation disabled until the updated rig projection, artifacts, witness
and existing live acceptance gates have been checked. A missing availability
metric must not be treated as a verified inactive transition or an authorization.

## Prepared controller and production image

Review the source and its [known local timeout limitation](../agent-physical-acceptance.md)
before rollout. The production MicroVM image context is prepared locally with
`just agent::cloud-package`; its entry point requires assignment verification.
The separate `just agent::controller-package` uses `nerdctl.lima` with the
existing Lima/containerd/BuildKit engine and
builds/tests an ARM64 controller ZIP under `tmp/`, including its runtime
libraries and source/build provenance. It records the provided.al2023 image
digest, checks dynamic linking in that image, and exercises bootstrap startup
without an AWS runtime endpoint. Check its printed SHA-256 and retain the build
logs. Verify the engine with `nerdctl.lima info`. BuildKit's local exporter
writes the controller artifact under repository `tmp/`; runtime checks use
`nerdctl.lima run` with networking disabled. These recipes do not call AWS.
The source package alone is not evidence that either ARM64 artifact runs.
The [2026-10-29 local build validation](../agent-cloud-build-validation.md)
records successful controller ZIP and production image builds through Lima,
including ARM64 tests and runtime smoke checks; live acceptance is still required.

For a local production-image build from the repository root:

```sh
just agent::cloud-package
nerdctl.lima build --platform linux/arm64 --progress plain \
  --tag txing-agent-cloud:local tmp/agent-cloud-package
```

Retain the image build log and its Linux ARM64 CTest results. This local tag
is for validation; production MicroVM image creation uses the operator-run AWS
procedure below.

### Lambda concurrency prerequisite and failed first deployment

The controller requires `ReservedConcurrentExecutions=1` to serialize launch,
assignment and orphan-repair work. Keep that reservation: shadow version checks
alone do not replace the controller-wide serialization assumption.

Before initial deployment, inspect `aws lambda get-account-settings --region
eu-central-1`. An account with only ten concurrent executions and ten unreserved
units cannot reserve one while retaining the service's unreserved minimum.
Request a regional **Concurrent executions** quota increase through AWS Service
Quotas; the standard published default of 1,000 provides headroom. Wait for the
approved limit to appear in account settings. Other accounts may have a larger
unreserved minimum; AWS validates the actual reservation. The deploy recipe
rejects an unreserved pool of ten or less before creating resources.
See [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
and [reserved concurrency](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html).

A failed initial stack at `ROLLBACK_COMPLETE` must be deleted manually before
recreating it; it cannot be updated in place. Inventory its resources first.
The artifact bucket has a retention policy and may remain after rollback or
stack deletion. Record its name and review it separately; the next deployment
creates a new bucket. Do not delete the shared bucket holding the controller
ZIP. After the operator deletes the failed stack and waits for deletion, rerun
`just agent::deploy` with the same reviewed controller object. The recipe ignores
`DELETE_COMPLETE` history while continuing to refuse an existing live/failed
stack. It never performs automatic deletion or removes the concurrency limit.

The controller ZIP must be uploaded by the operator to an existing S3 bucket
under an immutable, reviewed key before the first deployment. Set
`TXING_AGENT_CONTROLLER_BUCKET` and `TXING_AGENT_CONTROLLER_KEY` to that object,
then run `just agent::deploy`. This initial recipe refuses an existing agent
stack and creates the CloudFormation stack with its IoT rule, minute schedule,
and internal automation switch disabled. Its outputs include a separate image
artifact bucket, build/execution roles, log group and an unattached human
attachment policy. The operator grants the attachment policy to appropriate
principals. The agent execution role can read the agent shadow but cannot write
it; the controller is the sole operational writer.

Grant the attachment policy only to trusted operators. The client requests a
token scoped to port 8081, but the AWS token-creation permission itself is
image-scoped and does not force a caller to choose that port. A principal with
that permission can request a token for other ports, including the hook port;
do not distribute such tokens. The MicroVM proxy removes authentication
headers before forwarding requests, so the application cannot use those
headers to distinguish a wrongly scoped token from an internal hook request.

Build a **dedicated** production MicroVM image from the cloud package with the
stack's artifact bucket/build role and `agent/probe/hooks.json`. The
[disposable probe's image-build procedure](../agent-microvm-acceptance.md#operator-create-the-disposable-resources)
shows the AWS API shape and build verification; use the new cloud package,
production roles, a new dedicated image name, and the current source build ID,
not the probe image or its historical token. Inspect the managed base-image
availability, successful/active image version, ARM64 tests, source hashes,
snapshot-safe library resolution and post-restoration hook logs. Record the
image name and version. Image builds, storage, snapshots, logs and requests can
incur charges even while no MicroVM is running. Immutable publication and its
normal version-selection workflow are completed in #169.

Before enabling, complete the earlier accepted native, disposable MicroVM and
local physical gates; disable/drain the old system as above; verify the stopped
replacement shadow and the exact production artifacts and roles; and record the
operator and evidence. In the agent stack update, set `ImageName`,
`ImageVersion`, and semver `Release`, then set `PrerequisitesConfirmed=true`
and `AutomationEnabled=true`. The template requires these values and defaults
both switches to false. Keep a single dedicated image name across ordinary
release versions: the controller inventories that image and the role is scoped
to it. Changing the image name requires disabling automation and manually
draining every run of the old image first.

The controller must first observe the device inactive and then active. It does
not infer an activation from an already-active first observation, missing
metrics, an older source event, or a missed inactive interval. On expiry it
keeps the old budget until another directly observed transition. A long gap
after the last verified inactive observation can shorten or exhaust the next
budget. Never delete the agent shadow to restart the clock.

While an activation is verified active,
an ambiguous launch is retried with the same immutable request, including its
original relative MicroVM lifetime. If AWS first starts that request later, its
platform termination time can extend past the absolute activation deadline. The
runtime releases its device session at the deadline and the controller requests
termination, but a controller or AWS outage can leave the MicroVM running until
that later platform limit. The run hook rejects a request whose activation is
already expired or exceeds the 3000-second window, including when the deadline
passes during initialization. AWS may terminate a failed start, but that does
not prove termination of a host already accepted by the service. The operator
approved an independent, delayed [witness watch](agent-watch.md) on 2026-10-29
to repair this controller-failure case. It checks off assignments and expired
deadlines after a two-minute grace, using its own one-minute schedule, and also
cleans up aged unassigned instances of the dedicated image. Session or control
shutdown alone remains insufficient: live acceptance must show actual terminal
VM state. A shared AWS outage can still delay termination; the watch contract
records that dependency. Keep automation disabled until watch deployment,
controller-failure acceptance and the existing artifact/physical gates pass.
Within a reconciliation pass, the controller rechecks time around blocking
launch and assignment operations and uses steady elapsed time to avoid extending
the budget if the wall clock moves backward. A response received after expiry is
fenced and termination is requested; a lifecycle read older than fifteen seconds
is not promoted to a newly verified assignment.
When an image is configured, `AutomationEnabled=false` disables the lifecycle
trigger and leaves a termination-only minute schedule enabled. The controller
requests termination of every nonterminal VM in that dedicated image before
fencing known assignments, so slow Thing-shadow reads cannot prevent the VM
termination attempts. It processes inventory one page at a time so an error or
timeout on a later page does not discard earlier shutdown attempts. It retries
the full inventory until a pass contains no nonterminal VM;
an API failure or delayed schedule still prevents an immediate shutdown
guarantee. Initial deployment with the placeholder image keeps both triggers
disabled. The manual drain below remains necessary when automated cleanup cannot
complete or before changing the image identity.
If duplicate inventory entries disagree, a terminal or unknown entry cannot
hide a nonterminal entry for the same VM during that pass.
An invalid or missing automation setting, or an enabled controller missing its
required release or hosting configuration, also takes the termination-only
scheduled path and reports an error. If the image identity is missing, inventory
fails, or a saved assignment names a different image, the controller attempts to
stop known assignments only after the persisted launch
request, Thing/run/activation identity, and AWS-reported VM image agree and a
conditional shadow fence succeeds. The controller role remains scoped to the
stack's image. This fallback cannot discover unidentified orphans; a missing
or incorrect image identity still requires the operator to inventory and drain
the old image manually.

Reconciliation does not retry an unidentified launch when lifecycle cannot be
verified or after its reservation is fenced. The repair sweep can bind and
terminate a discovered runtime that reports the matching run identity. If no
runtime can be identified, the fence remains for that activation. A later,
directly observed and currently authorized activation can supersede the fenced
reservation only when it has no known VM ID. The controller conditionally saves
the new reservation before launch, never retries the old request, and rejects
late old results as unassigned. The independent witness watch must be configured
to clean up any aged old instance that cannot be associated with an assignment.
This retires the old assignment, not its compute; do not count it as terminal
VM evidence. Known VM IDs still require terminal confirmation before the run
is removed. Do not delete the shadow or restart an existing activation clock.

For a manual drain, set `AutomationEnabled=false` in the stack, confirm the
lifecycle trigger is disabled, disarm and release the owning client on the
secured device, and terminate each current or orphaned MicroVM of the dedicated image
using the operator's AWS credentials. Confirm the image inventory is empty of
nonterminal runs before changing image name or retiring the stack. Final released-cloud physical,
accelerated-expiry and zero-idle-compute evidence remains the separate #170
acceptance; prepared commands and local simulations do not satisfy it.

The repair sweep verifies an unlisted VM's runtime identity against the current
Thing and agent shadow before terminating it. If that identity or assignment
cannot be read, it skips that candidate and retries on a later pass rather than
terminating a potentially healthy VM. Its configured MicroVM lifetime remains
the final bound; inspect persistent failures and drain manually if required.
A missing agent capability shadow is not recreated during repair and does not
prevent independent devices from being reconciled; a VM candidate associated
with a missing shadow is still checked directly before termination.
Other per-device read failures also do not block checking unrelated candidates:
each candidate must independently prove its identity and current assignment
before termination, and unreadable candidates remain deferred.
An authenticated runtime report that its matching run has stopped is sufficient
to fence and terminate that run even if the device projection is unavailable or
stale. It cannot establish a new activation or publish a healthy endpoint.
The controller also persists the start of its own lifecycle-verification outage.
On a later pass after fifteen seconds of continuous failure it requests
termination unless authenticated status proves that the same running assignment
has recently verified its authority. Fetch time counts against that freshness
window. A fresh controller verification clears the timer; missing data is never
recorded as an inactive transition or used to extend the activation.
An event-triggered reconciliation that fails still attempts this stop-only check
before returning the original error for retry; it does not publish a healthy
sample from that failed reconciliation.
