# Cloud artifact and source-build acceptance

Status, 2026-10-31: #168 implementation/source-build acceptance is complete and
launches are disabled after cleanup. This record combines the original local
ARM64 builds through `nerdctl.lima`, operator-run AWS builds, witness repair and
bounded real cloud attachment/control checks. Diagnostic release 0.0.0 is
unpublished; immutable publication and final released-cloud physical acceptance
remain #169 and #170. All AWS writes were manual operator actions under the
[rollout runbook](constraints/agent-rollout.md) and
[witness watch contract](constraints/agent-watch.md).

The capability correction later on 2026-10-29 changes registry authorization and
Sparkplug agent availability. The refreshed build below includes that correction;
the original build is retained afterward as historical evidence.

## Refreshed capability build

Both `just agent::controller-package` and the documented local runtime-image
build completed on 2026-10-29 from clean source revision
`b90ff864ef864a65fe6c8ee494f55c8dea6c6af5`, after the operator deployed rig
`0.18.4`, shared Lambda `0.15.7`, Office `0.18.4`, and re-enlisted the TBot.

- Source-manifest/build ID shared by the controller and runtime:
  `f8d537fcfdf85cb5edcc2cb01b4654150d953f64beeb3297424096aa1b38a635`.
- Controller ZIP: `tmp/agent-controller.YjcgBa/artifact/controller.zip`.
- Controller SHA-256:
  `abe816fe4fb1bf8c6be8a37f47dbc3c8809a3bf4005add8adb9d7896ed3d6f6c`.
- Runtime source package:
  `tmp/agent-cloud-package/f8d537fcfdf85cb5edcc2cb01b4654150d953f64beeb3297424096aa1b38a635.zip`.
- Local runtime image:
  `txing-agent-cloud@sha256:81de9f9ffe5d4f8d6af478f7ee60dc83e1338fae61f162857caff67083701f86`.
- Both builds passed all eight Linux ARM64 CTest targets. The controller ZIP
  integrity, packaged dependencies, provided.al2023 runtime loading, and expected
  bootstrap startup failure without a Lambda runtime endpoint passed.
- An isolated runtime container passed the ready hook with a POST to
  `/aws/lambda-microvms/runtime/v1/ready` on port 8080. Its status endpoint on
  port 8081 reported `waiting-for-run`, empty credentials/identity and zero
  telemetry/video. Its build ID matches the controller. Image inspection confirms
  Linux ARM64, user `10001:10001`, and mandatory assignment verification. The
  temporary container was removed.
- Logs: `tmp/agent-controller-capability-build.log` and
  `tmp/agent-cloud-capability-build.log`. Runtime smoke evidence uses the
  `tmp/agent-cloud-capability-*` files; the controller retains `provenance/`.

Read-only AWS inspection confirms the TBot's current inactive projection has
`capability.agent=false` at REDCON 4, no non-terminated MicroVMs were returned,
the production agent stack is absent, and witness's image scope remains
`disabled`. The existing environment artifact bucket is available for the initial
controller upload. These observations do not establish cloud execution or watch
acceptance. The next operator step is the initial disabled stack deployment,
followed by a dedicated AWS image, witness configuration and live acceptance.

## AWS production image build

On 2026-10-29 the operator created the dedicated image
`arn:aws:lambda:eu-central-1:453102798330:microvm-image:town-agent`.
Read-only inspection confirms image version `1.0` has state `SUCCESSFUL` and
status `ACTIVE`. It uses managed AL2023 base version `2.0`, the production
stack's build role, ARM64/4096 MiB configuration, the configured hooks, and the
reviewed `f8d537fcfdf85cb5edcc2cb01b4654150d953f64beeb3297424096aa1b38a635`
source package in its artifact bucket.

AWS build logs independently record the source-manifest check
`agent/src/aws.cpp: OK`, all eight CTest targets passing, and `Machine: AArch64`.
This establishes the production image build and its managed hook validation;
real device streams, assignment, attachment and shutdown repair still require
live acceptance.

No non-terminated MicroVMs were returned for this image. At this checkpoint the
agent stack still has `ImageName=disabled`, automatic launches disabled, and
prerequisites unconfirmed; witness's image scope is also `disabled`. Next the
operator binds image `town-agent`, version `1.0`, while keeping launches disabled,
and deploys witness with that same dedicated image name. Image binding enables
the controller's termination-only minute schedule. It must be accounted for
when isolating the primary controller during later witness acceptance.

## Deployed watch preflight — 2026-10-30

The operator applied the image binding and witness deployment. Read-only AWS
inspection confirms both stacks are `UPDATE_COMPLETE`, the controller selects
`town-agent` version `1.0` with launches disabled and prerequisites unconfirmed,
and witness selects the same dedicated image. Both one-minute rules are enabled.
Recent controller and witness invocations finish without logged errors.

The original TBot's agent shadow remains version 1, `stopped`, with no run or
activation. Sparkplug version 1881 is born at REDCON 4 with
`capability.agent=false`. No nonterminal instances of the dedicated image were
returned. This is a deployed preflight checkpoint, not proof of actual MicroVM
termination. The next operator step is the controlled orphan test with the
primary controller isolated, as described in the
[watch acceptance instructions](constraints/agent-watch.md#isolate-the-controller-during-the-orphan-test).

## Live orphan shutdown acceptance — 2026-10-30

The operator paused the controller repair rule, set controller concurrency to
zero, waited beyond its 120-second timeout, and launched one deliberately
unassigned instance of image `town-agent` version `1.0`. Read-only checks
confirmed the controller rule disabled/concurrency zero and witness's independent
minute rule enabled.

- VM: `microvm-d47b635b-f9fd-37ac-b648-189faad47bc1`.
- AWS start time: **13:22:33.560 CET**.
- Observed `RUNNING` at **13:24:06 CET**, within the 120-second grace.
- Witness's exact-VM termination log: **13:24:57.471 CET**, age **143.911 s**.
- AWS terminal time: **13:24:57.800 CET**, age **144.240 s**; a subsequent
  `GetMicrovm` returned `TERMINATED`.
- The hosting cap was **600 seconds**, distinguishing this observed termination
  from platform expiry. No idle suspension policy was returned.
- A runtime status sample reported `assignmentVerified=false`, no attachment or
  held control, and zero telemetry/video. The original agent shadow remained
  version 1, stopped, with no run or activation.
- Final dedicated-image inventory returned no nonterminal instances.

The orphan path passes with the primary controller isolated. This does not
accept assigned off/deadline behavior, healthy/replacement preservation, device
streams, or cloud attachment. Controller restoration remains a manual operator
step; ordinary launches stay disabled. Evidence:
`tmp/issue-168/orphan-acceptance-result.json`, `orphan-observation-initial.json`,
`orphan-observation-latest.json`, `orphan-witness-bounded-events.json`,
`orphan-runtime-events.json`, `orphan-final-agent-shadow.json`, and
`orphan-final-nonterminal-inventory.json` under the same directory.

## Assigned-watch attempt rejected before acceptance — 2026-10-31

The first assigned-record attempt did not exercise witness shutdown. Its local
request contained `clientToken=watch-known-` and absolute deadline `600`, showing
that the timestamp shell variable was empty. AWS started
`microvm-ccde6987-1a3e-3ba1-9402-c434cdebbd9b` at 08:25:14.182 CET and terminated
it at 08:25:16.313 CET with the reason `Run lifecycle hook returned HTTP status
409`. The runtime correctly rejects an already-expired activation before device
initialization. The fixture's synthetic shadow reached version 2, but that does
not establish preservation or a witness termination.

Read-only inspection confirms no nonterminal instances remain, controller
concurrency is zero, its repair rule is disabled, and witness's rule is enabled.
The corrected local request helper generates the timestamp, token and deadline
together inside jq. Binding now rejects malformed identities, expired or
inconsistent deadlines and requests older than 60 seconds. Both request variants
pass the AWS input model; merged active/off records pass the shadow schema and
preserve activation identity. The rejected request is retained with the actual
VM evidence under `tmp/issue-168/known-invalid-*`. Retry only the launch/binding
section with a fresh request; known-assignment acceptance remains open.

## Synthetic assigned preservation checkpoint — 2026-10-31

The corrected request launched
`microvm-cd119808-f99f-3074-9e10-ef203a59ab56` at 08:30:21.107 CET. Its exact VM
identity was bound to the temporary `agent-watch-168` shadow at version 3, with
run/activation `watch-known-1793431820` and deadline 08:40:20 CET. A service read
at approximately 08:33:34 CET still reports `RUNNING`, beyond 180 seconds after
AWS start. The current synthetic record remains running and active, has no stop
timestamp, and retains the deliberately supplied media errors.

The primary controller is isolated (concurrency zero and repair rule disabled).
Witness's independent rule is enabled with the scheduled-watch event target;
invocations completed after the orphan cutoff without logged errors or a
termination request in the bounded capture. The real TBot shadow remains
version 1 stopped without run/activation. Evidence is retained in
`tmp/issue-168/known-preservation-acceptance-result.json` and the matching VM,
shadow and log snapshots.

This checkpoint establishes preservation of a synthetic, non-expired assigned
record beyond the orphan grace despite its media-error fields. It does not
establish real runtime/device health. Off-shadow grace and termination, the
separate deadline case and remaining live runtime/attachment acceptance are
still open. No deployment change is required; the next operator action is the
first off transition on this same fixture while keeping the controller isolated.

## Live synthetic off-shadow shutdown acceptance — 2026-10-31

After the assigned preservation checkpoint, the operator changed the temporary
fixture to shadow version 4, `stopping`/`active=false`, preserving its run and
activation. Its first `stopRequestedAt` is 1793432103 (08:35:03 CET). The exact
same VM, `microvm-cd119808-f99f-3074-9e10-ef203a59ab56`, was still `RUNNING`
84.886 seconds after off, during the required grace.

Witness logged its termination request at 08:37:57.452 CET, 174.452 seconds
after off. AWS records `terminatedAt` 08:37:57.956 CET, 174.956 seconds after
off and 456.849 seconds after start; the subsequent service state is
`TERMINATED`. This precedes both the unchanged 08:40:20 CET activation deadline
and the 600-second hosting cap. The off shadow therefore supplies independent
shutdown evidence for this test.

The primary controller remained unavailable (concurrency zero and repair rule
disabled), while witness's independent schedule remained enabled. The fixture
stayed version 4 with the same stop timestamp. Final dedicated-image inventory
has no nonterminal VMs. No manual termination was performed by the agent.
Structured evidence and the archived request/shadow/VM/log records are under
`tmp/issue-168/known-off-*`, including `known-off-acceptance-result.json`.

This accepts synthetic assigned off-shadow grace and compute termination.
Expired-deadline shutdown, real healthy/replacement preservation and live
runtime/attachment acceptance remain separate. No deployment change is needed.
Next, the operator launches and binds a fresh deadline-case VM while keeping
the controller isolated, leaves the fixture running through expiry, then
performs the documented fixture cleanup and controller restoration after all
test VMs are terminal.

## Live synthetic expired-deadline shutdown acceptance — 2026-10-31

The operator launched `microvm-32d9e848-4a7a-3cab-a3ab-dd1256ba3798` from
`town-agent` image version `1.0` at 08:39:40.316 CET. The temporary fixture's
shadow version 5 records run/activation `watch-deadline-1793432379`, deadline
1793432619 (08:43:39 CET), a running lifecycle and active controller state.
The previous off timestamp is absent. This test uses a 240-second hook deadline
and an independently later 600-second hosting cap.

AWS still reported `RUNNING` 115.597 seconds after expiry, within the required
grace. Witness logged the exact-VM termination request at 08:45:57.350 CET,
138.350 seconds after expiry. AWS records `terminatedAt` 08:45:57.675 CET,
138.675 seconds after expiry and 377.359 seconds after start; the subsequent
service state is `TERMINATED`, before the platform cap. Shadow state, metadata
and version are unchanged from the initial read: version 5 remains running/active
with the same deadline and no stop timestamp. Persisted expiry independently authorizes this
termination.

Final reads confirm controller concurrency zero and repair rule disabled,
witness schedule enabled, no watch errors in the bounded log capture, and no
nonterminal instances of the dedicated image. The real TBot shadow remains
version 1 stopped. Evidence and archived request/shadow/VM/log records are under
`tmp/issue-168/deadline-*`, including `deadline-acceptance-result.json`.

The orphan, synthetic off, synthetic deadline and synthetic assigned-preservation
cases have passed within their recorded scope. They do not establish real
runtime device/control release at expiry, healthy/reactivated real assignments,
physical attachment or the remaining live acceptance criteria. No code rebuild
or deployment change is required. After terminal confirmation, the operator
deletes only the temporary fixture's agent shadow and Thing, restores controller
concurrency one and its repair rule, and leaves witness enabled and ordinary
launches disabled.

## Watch batch cleanup and restoration — 2026-10-31

After the operator ran the cleanup block, read-only checks confirm controller
reserved concurrency one, its repair rule enabled, and witness's independent
schedule enabled. Both the temporary `agent-watch-168` Thing and its `agent`
shadow return `ResourceNotFoundException`. Dedicated-image inventory has no
nonterminal VMs. The production stack remains `UPDATE_COMPLETE` with
`AutomationEnabled=false`, `PrerequisitesConfirmed=false` and no selected release.
Restoration evidence is in `tmp/issue-168/watch-batch-restoration-result.json`.

The batch leaves no test compute or fixture registry/shadow resources. The
controller's minute schedule is restored to termination-only operation. Real
controller-driven startup, runtime/attachment and the remaining live acceptance
are still unverified; the real TBot currently projects `DDEATH`. Keep automatic
launches disabled while preparing those tests. Documentation changes require no
component rebuild or cloud rollout.

## Controlled source-build test approval and preflight — 2026-10-31

The operator explicitly approved one controlled source-build test using the
reviewed `town-agent` image version `1.0` with diagnostic release label `0.0.0`,
followed by restoring launches to disabled. This is a bounded exception to the
immutable-release enablement prerequisite and `run.release` meaning, not a
published agent release. Production publication remains #169. The exception
does not waive current assignment, device authority, physical readiness,
activation-budget, or cleanup requirements, and does not authorize agent-run
AWS mutations.

The read-only preflight confirms real TBot Sparkplug version 1885 has complete
DBIRTH metrics at REDCON 4 with `capability.agent=false`. Its agent shadow is
version 1 stopped without run/endpoint; dedicated-image inventory has no
nonterminal VMs. Controller concurrency is one and both independent repair
schedules are enabled. The stack remains disabled with the reviewed image and
controller object. Evidence and the approved request are under
`tmp/issue-168/controlled-preflight-*`, `controlled-test-approval.json` and
`proposed-test-enable.json`.

The next manual step applies only the reviewed enablement parameters and waits
for stack completion while the TBot stays at REDCON 4. The enabled controller
must then persist its own verified inactive observation before the operator
selects an active REDCON. Observation without a manual attachment precedes
the native attachment test. The prepared disable request restores both
switches false and the release field empty afterward. No startup or attachment
acceptance is claimed at this preflight checkpoint; no rebuild is required.

### Enabled controller inactive checkpoint

The operator applied the approved test update. Read-only verification confirms
`UPDATE_COMPLETE`, both enablement parameters true, diagnostic release `0.0.0`,
and the reviewed controller/image references. The function update succeeded,
controller concurrency remains one, and its minute rule is enabled.

At 09:01:09 CET the enabled controller persisted real agent-shadow version 2
with `observed=true`, `active=false`, `inactiveObservedAt=1793433669`, projection
version 1885 and source timestamp 1793433230462. The real device remains DBIRTH
at REDCON 4 with agent availability false. Its agent is stopped without a run
or endpoint; no nonterminal VMs were returned. No synthetic write or history
reset was used. The scheduled invocation completed; missing-shadow diagnostics
for other registry entries use the sweep's explicit handled missing-shadow path.
Evidence is `tmp/issue-168/controlled-inactive-checkpoint-result.json` and the
`controlled-enabled-*` snapshots.

The next manual step is normal REDCON 1 activation, followed by controller-run
and stream observation before any human attachment. Startup, real streams and
attachment remain unverified at this checkpoint. Restore launches disabled and
confirm all VMs terminal at the end of this bounded test.

## First real controller startup: video defect — 2026-10-31

After the operator selected REDCON 1, the controller created run
`32D61AA6-6784-4691-9816-88B7B7515A77`, activation
`7778BED2-C029-4002-8B78-204DDD1A8C69`, and VM
`microvm-ae2d7e80-a9e5-3ceb-9f25-677cca9e176f` from image `1.0`. AWS start time
is 09:05:08.769 CET. The activation preserves start 1793433904 and deadline
1793436904, a 3000-second budget; the hosting request uses its remaining 2996
seconds. No synthetic shadow update or manual VM launch was used.

The runtime verifies its exact assignment, connects MAVLink and records real
telemetry messages while reporting no attachment and no held control. The
controller publishes the current endpoint and a matching runtime sample.
However, video remains disconnected with zero frames despite the real
Sparkplug projection being REDCON 1. Office video is a separate connection.
Code inspection found that the assigned cloud path returned a hardcoded
`Lifecycle{true, 2}`, preventing Session's REDCON 1 video gate from opening.
This attempt does not pass complete stream or attachment acceptance.

The operator returned REDCON 4 and applied the prepared disable update. AWS
records actual termination at 09:08:04.544 CET. Subsequent reads confirm
`UPDATE_COMPLETE`, both launch switches false, Release empty, a stopped agent
without a run and no nonterminal VMs. The activation history was retained.
Evidence is `tmp/issue-168/controlled-first-run-result.json`, sanitized runtime
samples and the matching service/shadow/log snapshots.

The repair carries actual REDCON in transient projection metadata from the
same verified shadow read and preserves it through the production assignment
gate. No extra AWS read, persisted schema change or activation-budget change
is needed. A regression reproduced the old behavior by failing to start the
video stream, then passed with REDCON preserved. It checks video receipt,
REDCON 1-to-2-to-1 video stop/restart without replacing MAVLink or the activation,
and stale/pending/replaced/deadline-mismatched/revoked assignment rejection.
All eight native CTests and 25 Python checks pass after the fix.

The new source-manifest ID is
`0161b1245673580c33741051c4322ce8e405588dcae38405e9d34e0c868f17ea`;
its source ZIP SHA-256 is
`6540a3b616aecd9c64f002c7fd696b206fca3f6fb9ac0987ce919367678de811`.
The local ARM64 controller build also passes all eight CTests, including the
runtime regression. The fresh ZIP is
`tmp/agent-controller.MAEWwL/artifact/controller.zip`, SHA-256
`e78bb1678c3b855452c3fe393a23813349be523f5dc40d8a9f57a01fd1a8d21e`.
It shares the source manifest above and passes AArch64 ELF, ZIP integrity,
provided.al2023 dependency resolution and the expected bootstrap-startup check.
Its validation runtime is
`public.ecr.aws/lambda/provided@sha256:190401153d110031bb5e933b1eaa78a0f2cb5a7710bdc7464f86315d09f0f836`.
Build/test/evidence logs are under `tmp/issue-168/video-redcon-*`.

The local controller build does not establish the new runtime image's hooks or
live video; the later AWS image-build result is recorded below.
Deployed image `1.0` still contains the defect. Keep launches disabled; upload
the reviewed packages and build a new image version using the complete preserved
configuration in `video-redcon-update-image.json`. Verify its actual successful
version and bind reviewed controller/image artifacts while disabled, then repeat
startup/video observation before attachment. No shared Go Lambda, rig, board or
Office release bump is required by this C++ runtime repair.

### Image update request correction

The first repair-image update was rejected with `ValidationException` because
the prepared request copied `baseImageVersion="2.0"` from AWS's read response.
The write operation requires a single major version, `"2"`. The client input
model accepts both strings and therefore did not catch this service-side rule.
Read-only inventory still contains only successful/active image `1.0`.

The corrected local request normalizes the base selector to `"2"` and uses a
stable hash of the corrected complete payload as its idempotency token after
this definitive validation rejection. All other request fields are unchanged.
It passes the AWS input model plus an explicit major-only format check.
Both S3 artifacts exist with the expected sizes, and their local SHA-256 values
are unchanged. No rebuild or repeated upload is needed; the operator retries
only the corrected image-update request and polls version status. No AWS write
was performed by the agent.

## Repair image 2.0 verified in AWS — 2026-10-31

The operator retried the corrected image request. Read-only inspection confirms
`town-agent` version `2.0` is `SUCCESSFUL` and `ACTIVE`, with the exact reviewed
`0161b1245673580c33741051c4322ce8e405588dcae38405e9d34e0c868f17ea`
source URI, production build role, managed base, ARM64/4096 MiB resources,
connectors and hooks. AWS build logs verify the changed source and regression
files against the manifest, pass all eight CTests, and identify the executable
as AArch64. Image ready/validate hooks are enabled and service build completion
is successful. Evidence is `tmp/issue-168/video-redcon-image-2-build-result.json`,
the exact image snapshot and captured AWS build/hook logs.

The matching controller ZIP SHA-256 is
`e78bb1678c3b855452c3fe393a23813349be523f5dc40d8a9f57a01fd1a8d21e`.
The prepared, offline-validated `video-redcon-bind-artifacts.json` pins that
controller object and actual successful image version `2.0`, while explicitly
keeping both enablement switches false and Release empty. Other stack
parameters and the template retain previous values.

Pre-binding reads confirm the stack is still `UPDATE_COMPLETE`, selects the
old image/controller and has launches disabled, with no nonterminal VMs.
The next operator step applies only this disabled artifact binding and waits
for completion, leaving the TBot at REDCON 4. Verify both new references before
repeating the approved controlled source-build test. This accepts image-build
provenance and checks; it does not establish live cloud video or attachment.
No AWS mutation or commit was executed by the agent.

### Repaired artifacts deployed with launches disabled

The operator applied the disabled binding. Read-only inspection confirms stack
`UPDATE_COMPLETE`, image version `2.0` and the matching controller object.
Lambda's actual `CodeSha256` matches the reviewed ZIP digest in base64;
its function state/update are successful and the environment selects image 2.0
with automation disabled. Both enablement switches remain false and Release is
empty.

The TBot is DDATA at REDCON 4 with agent availability false (Sparkplug version
1893). Its agent shadow version 30 is stopped without run/endpoint, its original
activation record is retained, and no nonterminal VMs exist. Evidence is
`tmp/issue-168/video-redcon-bound-checkpoint-result.json` and the corresponding
stack/function/shadow/inventory snapshots.

The next manual step continues the approved controlled source-build test with
`video-redcon-enable-test.json`, explicitly pinning image 2.0 and the matching
controller, diagnostic label 0.0.0 and both switches true. Keep REDCON 4 until
the updated enabled controller freshly records inactive; only then activate
normally and require actual cloud video before attachment. The existing disable
request restores both switches false and Release empty after the bounded test.
No AWS mutation or commit was executed by the agent.

### Repaired enabled controller inactive checkpoint

The operator enabled the approved source-build retry. Read-only verification
confirms `UPDATE_COMPLETE`, exact controller code hash, image 2.0, both switches
true and diagnostic release 0.0.0. The updated enabled controller wrote agent
shadow version 31 with `observed=true`, `active=false` and a fresh
`inactiveObservedAt=1793435949` (09:39:09 CET), advanced from 1793434090.
The old activation remains unchanged; no run, endpoint or nonterminal VM exists.
The device is still DDATA at REDCON 4 with agent availability false.

Evidence is `tmp/issue-168/video-redcon-enabled-inactive-result.json` and the
matching service/shadow snapshots. The next operator step is normal REDCON 1
activation while leaving manual attachment off, followed by actual cloud
telemetry/video verification. Live video and attachment acceptance remain pending.

## Repaired real unattached cloud observation — 2026-10-31

Normal REDCON 1 activation launched exactly one image 2.0 VM,
`microvm-1231774d-edb8-354f-b24c-7a24c7b40eca`, at 09:41:50.823 CET.
Its run `0DD7A8D6-B49D-410C-8A40-43D36657BC30`, activation
`E12954CC-BDA8-4C9D-BA3F-ABDCE10E1730` and deadline 1793439106 remain unchanged.
The activation budget is 3000 seconds. No synthetic shadow or manual VM launch
was used.

Runtime samples identify the reviewed source build and fresh verified assignment,
connected MAVLink and H.264, and increasing telemetry/video counters with
nonempty encoded-frame metadata. Every parsed sample reports no attachment and
no held control. The same VM remains running beyond 180 seconds, later controller
samples retain both streams under that assignment, and witness has no recorded
termination request for it. Inventory contains exactly one nonterminal VM.
Interleaved non-JSON log lines are excluded from diagnostic parsing.

The board's pre-attachment MAVLink shadow reports two connected peers, both
observers, and `armed=false`; UDP port 14551 is free at preflight. The next
operator step is one observation-only native attachment using QGC's existing
14550/14551 link, retaining the Office peers for comparison. Require live QGC
telemetry, cloud attachment/no held control, unchanged VM/run and board peer
counts before detach checks. Native attachment and physical-control acceptance
are still pending.

Evidence is `tmp/issue-168/video-redcon-retry-observation-result.json`, exact
service/shadow/runtime/witness captures, and `cloud-attach-before-*` baselines.
The operator must still return REDCON 4, confirm actual terminal VM state and
restore launches disabled after this bounded source-build test. No AWS mutation,
token creation, device control or commit was executed by the agent.

## Observation attachment and client cutoff — 2026-10-31

The operator ran the observation-only native attachment and reported increasing
QGC heartbeats. Cloud runtime samples show `attached=true`, `controlHeld=false`,
fresh assignment and increasing telemetry/H.264 counters on the same VM, run,
activation and deadline. Board MAVLink peers stay two connected/two observers,
with `armed=false`, before, during and after attachment.

The operator confirmed the terminal message `Attachment token lifetime ended`.
The last attached sample is 09:52:22.465 CET and first detached sample
09:52:27.480 CET, consistent with the client cutoff roughly four minutes after
the first attached sample at 09:48:26.792 CET. The local UDP listener is gone;
cloud streams continue afterward without replacement or deadline change.
This is the client-enforced cutoff, not AWS server-token expiry. The observer
held no lease, so held-control release remains a separate check.

Evidence is `tmp/issue-168/cloud-attach-observer-result.json` and the exact
runtime, shadow and peer-count snapshots. A fresh preflight confirms ready link,
fresh heartbeat, disarmed state, two observers and the same running cloud agent.
The next manual phase explicitly requests a free lease with `--control`, then
checks client-inactivity release and no automatic reacquisition. Arming/motion
and final released-cloud physical acceptance remain separate. Finish this
bounded source-build test with REDCON 4, actual terminal VM confirmation and
launches disabled; no real activation history is reset.

## Explicit cloud free-lease grant — 2026-10-31

The operator started a new explicit `--control` attachment and reported
`control=1 cloud agent control state`. Board MAVLink shadow version 1332 confirms
actor QGroundControl, epoch 1, session `mavlink-2` and a 5000 ms lease, while the
vehicle remains disarmed. Connected peers remain two; observers drop from two
to one. The grant reuses the existing cloud device connection.

Fresh runtime samples show attached/held/assignment-verified true, both media
connections intact and counters increasing. The single image 2.0 VM, run,
activation and deadline remain unchanged. The initially read controller sample
predates this grant; current board authority and runtime logs provide the grant
evidence. See `tmp/issue-168/cloud-control-held-result.json` and exact snapshots.

The next operator step disconnects only the QGC UDP link, retaining the native
attachment, to verify client-inactivity release and then no automatic grant on
QGC reconnection. No arming/motion is included. The bounded test still requires
REDCON 4, terminal compute confirmation and disabled launches at completion.

## Client-loss fencing and final shutdown — 2026-10-31

After the operator disconnected only the QGC UDP link, the held lease was
released while the WebSocket remained attached. Runtime control changed from
held to lost with `client inactivity or lease expiry`; both media connections
continued. Board shadow version 1334 has no active owner, two observers and a
disarmed vehicle in Hold. The operator reported heartbeats resumed after
reconnecting that same link; no held-control sample or board regrant was observed
through the remaining attachment window. The terminal then reported control
zero, attachment closed and the expected client lifetime cutoff. The disconnect
wall-clock instant was not captured, so this is release/fencing evidence rather
than a precise measured five-second latency claim. It is also not a claim of
AWS server-token expiry. See `tmp/issue-168/cloud-control-loss-result.json`.

The operator selected REDCON 4 while leaving controller automation enabled.
AWS confirms the same image 2.0 VM reached `TERMINATED` at 10:16:37.232 CET,
after a 2086.409-second lifetime, before its activation/platform deadline.
The agent is stopped without a run or endpoint, the original activation remains
intact, and no nonterminal VMs remain. No witness termination request for this
VM appears in the bounded shutdown window. See
`tmp/issue-168/repaired-normal-shutdown-result.json` and service/shadow/log data.

The operator then applied the prepared disable update. Final reads confirm
`UPDATE_COMPLETE`, image 2.0 and the matching controller, both enablement switches
false, Release empty, controller concurrency one, and both minute repair rules
enabled. The agent shadow is stopped at version 129 with activation history
retained; inventory contains zero nonterminal VMs. No automatic rollout or
rearming is left enabled.

## #168 implementation acceptance and limits

The implementation criteria use the following complementary evidence. Automated
tests establish injected races and boundary cases; the operator-run AWS checks
establish the specific live paths described above.

| Requirement | Evidence |
| --- | --- |
| Capability/lifecycle reconciliation and one current run | C++ controller integration/reconcile tests; real inactive-to-active image 2.0 startup, one VM and normal inactivity termination |
| Persisted launch identity and budget across retries/replacements | Activation/reconcile/controller integration tests, including ambiguous launch, version conflicts and release changes; unchanged live run/activation/deadline through attachments |
| Expiry and no rollover | Actual C++ deadline/fencing tests and accelerated state-machine checks; live witness deadline repair. Full released-runtime accelerated boundary acceptance remains #170 |
| Controller-owned diagnostics and stale endpoint fencing | Conditional shadow/runtime-sample tests plus real current endpoint, run identity, connection/control errors and final endpoint removal |
| Independent streams and current runtime assignment | Real unattached MAVLink/H.264 on the reviewed source; REDCON regression, recovery and stale-assignment tests |
| Native authenticated attachment | Real operator-run attach, QGC heartbeat receipt and four-minute client cutoff; token/port/loopback tests |
| One attachment, shared peer/lease, loss fencing | Exclusivity/token tests; actual free-lease epoch, unchanged board peer count, client-loss release and no observed reacquisition after reconnect |
| Managed hosting and zero inactive compute | Deployed stack/configuration, automatic unaccompanied observation, actual terminal VM and empty final inventory |
| Automated integration coverage and enablement gates | Eight native CTests, 25 Python checks, eight local ARM64 CTests, eight AWS ARM64 CTests; prior coordinated rig/witness/Office/catalog checks and deployed gate verification |
| Independent witness shutdown repair | Live orphan, synthetic off/deadline grace and terminal-state evidence with primary controller unavailable; real healthy/reactivated image 2.0 run retained; bounded failure/pagination tests |

This closes the #168 implementation/source-build scope after cleanup. The
diagnostic release 0.0.0 was an explicitly approved unpublished test exception;
no immutable release has been published. #169 publication and #170 released
GUI parameter/motion/contention/fault/accelerated-duration/cost acceptance are
not completed or started by this record. The earlier #167 intermittent transport
timeout remains a known limitation; this healthy source-build run does not
establish that its cause was fixed. Shared AWS outages can delay watch repair,
and missed inactive intervals retain the operator-approved fail-closed behavior.

The immutable acceptance artifacts remain the frozen build recorded above.
Post-acceptance README/status documentation updates do not rebuild or replace
those objects; the runtime/controller source and tests remain unchanged from
that validated build. Keep launches disabled pending the later release gates.
No commit, AWS mutation, firmware action or legacy-resource cleanup was executed
by the agent.

## Original build (historical)

## Source and tooling

- Source revision: `c13a157f96d0f968f6d4939aa00fb507388931cc` with the uncommitted
  #168 implementation. This is not a published immutable release.
- Verified source-manifest/build ID shared by controller and runtime:
  `d014d8554b489670e86162e055b6e03af456970f0757236dcdb9bea3c660e0ac`.
- Engine: nerdctl `v2.4.1`, BuildKit `v0.33.1`, containerd `v2.4.1`, Linux ARM64.
- A scratch-stage local-export check and an isolated Alpine bind-mount check
  passed before the artifact builds.

## Controller ZIP

`just agent::controller-package` completed successfully through `nerdctl.lima`.
All eight CTest targets passed in the Linux ARM64 build. `readelf`/`file` identify
the exported bootstrap as an AArch64 Linux ELF. The ZIP integrity check passes.

- ZIP: `tmp/agent-controller.rnNnn5/artifact/controller.zip`.
- SHA-256: `ce771004d64f8bbac1dce0af575ad6c7587871f756aa40e9ef55f13eb4b244ab`.
- Validation runtime:
  `public.ecr.aws/lambda/provided@sha256:e0a5c70ae7962e83bcc5a6deada474a1646e2d0df5136607c0f21190403272ee`.
- In that runtime, with networking disabled, dependency loading found every
  library and bootstrap startup without a Lambda runtime endpoint produced the
  expected `Lambda runtime API address is invalid` failure.
- `provenance/` retains engine versions, source hashes, package versions,
  ELF details, runtime digest, link results and bootstrap output.
- Full successful build log: `tmp/agent-controller-lima-build-final.log`.

## Production runtime image

The documented command completed successfully:

```sh
nerdctl.lima build --platform linux/arm64 --progress plain \
  --tag txing-agent-cloud:local tmp/agent-cloud-package
```

All eight CTest targets passed in this build too. The final image's library
checks passed and image inspection confirms Linux ARM64, user `10001:10001`,
and the mandatory `--require-assignment` entry point.

- Local image digest:
  `txing-agent-cloud@sha256:63027f22329e5cb7dafa2e2eab5e62a4cee079f2dbb61b860b0726de837259c7`.
- Build log: `tmp/agent-cloud-lima-build.log`.
- An isolated container passed the ready hook and reported `waiting-for-run`,
  empty identity/credentials and zero telemetry/video counters. Its embedded
  build ID matches the controller and source package. The temporary container
  was removed after validation.
- Smoke evidence: `tmp/agent-cloud-lima-ready.json`,
  `tmp/agent-cloud-lima-status.json`, `tmp/agent-cloud-lima-image.json`, and
  `tmp/agent-cloud-lima-smoke.log`.

## Findings and limits

The first ARM64 test run caught unsigned EC2 metadata probing in the offline
controller fixture before its explicit region was assigned. Both controller
fixtures now disable IMDS at configuration construction and retain the
signed-request assertion. The Lambda package check also corrected the loader
path to `/lib/ld-linux-aarch64.so.1`, as present in `provided.al2023`.

The successful final run includes both corrections. Earlier failed logs remain
under `tmp/agent-controller-lima-build.log` and
`tmp/agent-controller-lima-build-fixed.log`.

These artifacts do not prove AWS image activation, snapshot/restore behavior,
execution-role permissions, real KVS streams, cloud attachment or terminal VM
state after controller failure. No device run hook, AWS resource mutation,
publication, firmware flashing or commit occurred during these checks. Keep
automation disabled until the existing deployment/live acceptance gates pass.
