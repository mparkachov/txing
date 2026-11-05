# Released cloud physical acceptance — #170

Status: **in progress; secured QGC flow and bounded loss subcases accepted;
full released-cloud acceptance remains open**.
Selected on 2026-11-02 after #169 closed. This record covers the released
system, real TBot and QGroundControl. Historical
[#168 source-build checks](agent-cloud-build-validation.md) and automated tests
support diagnosis but cannot complete this gate.

Current rollout checkpoint: release **0.1.1**, image **4.0**, matching controller
and normal budget **3000** remain selected. Released QGC parameter retrieval
and the secured/lifted arm/drive/disarm/re-arm sequence pass under one
session-owned lease. Client/attachment loss, real UDP-path loss, Office busy
rejection and explicit takeover/lease loss are verified. The timed registry
denial below now demonstrates held-control verification loss, stale ingress
closure and an unheld observer replacement preserving the same deadline.
The duration/replacement criterion and operator cost/publication acknowledgement
are accepted. The independent released-image witness orphan test also passes,
with controller restoration and repeated zero-compute inventory verified.
Independent video/REDCON 2/1 behavior now passes in the separately recorded
directional cases below, including fresh actual-2 startup and same-worker
video recovery with an unchanged telemetry peer. The November 3 closeout
verifies actual REDCON 4, terminal compute and both launch gates false, with a
second drained inventory more than two minutes later. The November 5 synthetic
assigned-record witness checks below now pass. Their fixture is removed,
controller concurrency/repair are restored, and an independent complete
five-image inventory remains drained in a later repeat check. Both
ordinary launch gates stay false and the real device remains inactive.
Whole-device DDEATH acceptance remains pending physical access. The operator's
2026-11-05 scope decision moves the three runtime findings into independent
follow-ups outside milestone 10; their remedies do not block its completion.
No repair is claimed. The separate Scheduler migration was
deployed after the timed cutoff, before observer replacement.

## Independent runtime follow-ups — 2026-11-05 scope decision

The operator explicitly selects separate tracking outside every milestone:

- [#172](https://github.com/mparkachov/txing/issues/172): intermittent MAVLink/control stalls.
- [#173](https://github.com/mparkachov/txing/issues/173): fatal camera cleanup hangs and recovery.
- [#174](https://github.com/mparkachov/txing/issues/174): board IoT credential renewal/session disruption.

These findings retain their evidence and unresolved status, but their remedies
are outside milestone 10 and are not dependencies or blockers for #170 or that
milestone. Historical checkpoints below preserve what was known at each time;
this scope decision supersedes their statements that these remedies keep the
milestone open. Creation of the follow-ups does not select implementation.
Existing safety/authority behavior, the 3000-second limit and the remaining
real released-system acceptance requirements stay intact. In particular, the
physical whole-device DDEATH check remains in #170. The separate battery
hardware disposition of closed #171 remains unchanged.

## Identity and initial read-only checkpoint

Read-only AWS responses captured on 2026-11-02 at 08:08–08:09 UTC show:

- Frankfurt stack `town-agent` is `UPDATE_COMPLETE`, selecting release `0.1.0`,
  dedicated image `town-agent` version `3.0`, and
  `agent/0.1.0/controller.zip`. Both launch switches are false.
- Image ARN:
  `arn:aws:lambda:eu-central-1:453102798330:microvm-image:town-agent`.
  The controller's SHA-256 matches the accepted 0.1.0 publication:
  `2173c3565b33141e71773131d348d4c5324012cac6ac5a10e5ba487fb3c7ddb1`.
- The dedicated-image inventory is empty. TBot `tbot-8yzfgj` is born at
  REDCON 4 with `capability.agent=false`; its agent shadow is stopped without
  a run/endpoint. Its prior activation history remains intact.
- Current checkout is `8d7cd042`; the immutable 0.1.0 runtime/controller source
  remains `eb17bdcd48efbbd910738d851c62149d906b9254`.

Raw responses are under `tmp/issue-170/preflight-*`, including the stack,
resources, controller/configuration/concurrency, image version, complete VM
inventory, registry Thing and both shadows. These are a dated baseline, not
proof of later shutdown or physical readiness. Record current operator,
board/rig/Office versions, board boot/credential age, QGC version, source and
executable checksums with each live run. Confirm secured/lifted, wheels clear
and initially disarmed before any control test.

Further reads confirm controller reserved concurrency one, its repair rule
enabled, and the witness's independent minute schedule enabled for this exact
image. The historical `town-tbot-companion` stack does not exist; VPC/NAT
lookups by that stack's and `town-agent`'s CloudFormation tags return no matches.
These scoped tag queries do not prove absence of all retained/untagged legacy
networking; final operator inventory remains pending.

## Acceptance matrix

Every row requires timestamped operator-run evidence on the released system.
Record commands, exit results, UTC times, raw AWS responses/log windows, VM/run/
activation identities, board authority and physical observations. Keep secrets,
attachment tokens, SDP and TURN credentials out of evidence and tracker posts.

| Case | Required observation | Status |
| --- | --- | --- |
| Identity | Exact GitHub release/source/build hashes, image version, controller code hash, Frankfurt stack and native attach executable; device/QGC/commands/logs | Released 0.1.1/image 4.0 identities verified below; final outcomes still being collected |
| Unattached startup | Normal inactive→active starts one authorized released VM; no attach process; increasing real telemetry and encoded video counters/metadata; observation only | Verified bounded live run below; remaining cases separate |
| REDCON 2/1 | Actual lifecycle 1→2 stops video alone, preserves MAVLink and run/deadline; 2→1 restores video; fresh actual-2 activation receives MAVLink only | Verified in separate directional cases: camera-only 1→2, fresh actual-2 entry, and video-config retry 2→1 with unchanged worker, telemetry peer and run/deadline |
| QGC physical flow | `just agent::attach … --control`, real parameter retrieval, arm/drive/disarm/re-arm on secured lifted TBot; same session-owned lease across disarm/re-arm; final disarm/release | Verified live below |
| Contention | Office owns lease first: agent requests `takeover=false`, stays observer; explicit Office takeover of held agent control revokes it; no automatic regrant after Office release | Busy rejection and explicit takeover/no regrant verified below |
| Client/attachment loss | Separately measure QGC inactivity and attachment disconnect while holding control; board releases/disarms, healthy cloud observation continues; reconnect never reacquires | QGC inactivity and Ctrl+C attachment closure verified below; exact click-to-release timing was not retained |
| WebRTC/lease loss | Real MAVLink transport loss and real lease loss revoke control; returning transport stays observer; video-only fault preserves healthy telemetry, records independent error and recovers independently | Real UDP-path loss/recovery without regrant and Office lease loss verified; camera-only failure preserves telemetry/error separation, and video-config retry demonstrates independent recovery; fatal camera-cleanup finding remains open |
| Lifecycle/assignment evidence | Real denied/unavailable verification stops authority by fifteen seconds; stale endpoint/attachment is unusable; recovery cannot manufacture a new activation | Verified timed registry denial: sampled transition at 14.961–15.285 seconds of verification age, board release, stale ingress closure and unheld replacement under unchanged activation/deadline |
| Repeated/delayed events | Deliver duplicate/stale event hints to the released controller while inspecting current projection; one authorized run and unchanged deadline; old endpoint/runtime identity never restores authority | Duplicate/delayed hints and expired attach refusal verified in duration test; timed loss adds stale ingress closure/no duplicate sampled VMs; independent video recovery now verified below |
| Duration/replacement | Accelerated activation expires at its saved deadline, replacement gets remaining budget, configuration/publication cannot extend it, continued activity never rolls over; verified inactive→active permits a new activation | Verified 600-second replacement/expiry/no rollover, expired refusal, then observed reactivation with restored 3000-second allowance |
| REDCON 3/4/death | Each real lifecycle condition stops authority and yields terminal AWS VM state plus complete empty nonterminal inventory; no stale usable endpoint | Actual REDCON 3 and 4 terminal states verified; device death pending |
| Cost/operations | Inventory agent networking/legacy resources; operator acknowledges remaining storage/log/snapshot/API/event/data costs and immutable publication/manual disarm-and-drain replacement | Inventory recorded and operator acknowledgement accepted; no zero-total-charge claim |

Failures remain in this record and the open issue with exact evidence. The
[#167 intermittent MAVLink/control timeout](agent-physical-acceptance.md#timeout-record-and-closure-decision--2026-10-28)
is unresolved; publication and a healthy short run do not establish its repair.
Board renewal can interrupt earlier than fifty minutes; see the
[duration limitation](constraints/agent-session-limit.md).

## Release prerequisite for accelerated acceptance

Release 0.1.0 hardcodes 3000 seconds and has no accelerated controller setting.
The #170 change prepares **agent 0.1.1** with CloudFormation
`ActivationBudgetSeconds` and controller environment
`TXING_AGENT_ACTIVATION_BUDGET_SECONDS`. Default/missing setting is 3000; only
integer values 1–3000 are valid. Invalid settings fail configuration and use
termination-only repair. The runtime, persisted shadow and hosting request
retain the hard 3000-second maximum.

The setting applies only when the controller observes a new activation. Saved
activation identity/start/deadline and exact launch retries survive changing the
setting, replacement and publication. Changing the setting does not shorten or
extend an already-created activation. Never delete/reset/write the agent shadow
or forge lifecycle messages to create time budget.

Local preparation passes eight native CTest targets and forty Python checks,
including a shortened persisted activation, replacement/configuration changes,
expiry/no rollover/reactivation, invalid-setting drain, and the actual AWS SDK
wire request's remaining duration. `cfn-lint`, POSIX shell parsing and ShellCheck
pass. Logs are `tmp/issue-170/local-tests.log`, `cfn-lint.log` and
`versioned-build.log`. The first ARM64 attempt could not reach Lima; after the
operator started the existing engine, the local 0.1.1 candidate passed the
additional checks below. No release/deployment or live acceptance is inferred
from the local checks.

The operator committed/pushed the changes as `a05504aa`. The clean immutable
`agent-v0.1.1` GitHub release passed the
[publication workflow](agent-release-publication.md#build-and-release) and the
independent archive audit recorded below. The operator published it with
`TXING_AGENT_BASE_IMAGE_VERSION=2 just agent::publish 0.1.1`; image **4.0** and
its matching controller are now selected with both launch switches false.
The separate budget-template update subsequently passed verification. Preserve
the printed evidence folder and verify the selected image/controller checksums.
**Do not reuse image version 3.0 as evidence for the changed controller.**
Keep both switches false and the device inactive throughout this rollout.

Ordinary publication uses the existing CloudFormation template. It does not
install new template parameters. After successful publication, the operator
applies the verified **release's** `stack.yaml` to the existing disabled stack:

```sh
# Repository root, operator terminal. Retain the printed evidence path.
if sh <<'TXING_AGENT_TEMPLATE_ROLLOUT'
set -eu
eval "$(just _project-aws-env aws '')"
export AWS_PAGER='' AWS_DEFAULT_REGION=eu-central-1
mkdir -p tmp
evidence=$(mktemp -d "$PWD/tmp/agent-cloud-acceptance.XXXXXX")
printf 'Evidence: %s\n' "$evidence"
gh release download agent-v0.1.1 --repo mparkachov/txing \
  --pattern txing-agent-release-linux-arm64.zip --dir "$evidence"
unzip -q "$evidence/txing-agent-release-linux-arm64.zip" -d "$evidence/release"
(cd "$evidence/release" && shasum -a 256 -c SHA256SUMS)
aws cloudformation describe-stacks --region eu-central-1 \
  --stack-name "${TXING_AWS_STACK}-agent" > "$evidence/template-before.json"
jq -e '.Stacks[0] | .StackStatus=="UPDATE_COMPLETE" and
  (.Parameters | map({key:.ParameterKey,value:.ParameterValue}) | from_entries |
    .Release=="0.1.1" and .AutomationEnabled=="false" and .PrerequisitesConfirmed=="false")' \
  "$evidence/template-before.json"
jq '.Stacks[0].Parameters |
  map(select(.ParameterKey!="ActivationBudgetSeconds") | {ParameterKey,UsePreviousValue:true}) +
  [{ParameterKey:"ActivationBudgetSeconds",ParameterValue:"3000"}]' \
  "$evidence/template-before.json" > "$evidence/template-parameters.json"
# Review the release template and parameter file before this manual AWS update.
aws cloudformation update-stack --region eu-central-1 \
  --stack-name "${TXING_AWS_STACK}-agent" \
  --template-body "file://$evidence/release/stack.yaml" --capabilities CAPABILITY_IAM \
  --parameters "file://$evidence/template-parameters.json" > "$evidence/template-update.json"
aws cloudformation wait stack-update-complete --region eu-central-1 \
  --stack-name "${TXING_AWS_STACK}-agent"
aws cloudformation describe-stacks --region eu-central-1 \
  --stack-name "${TXING_AWS_STACK}-agent" > "$evidence/template-after.json"
printf 'Template update completed. Evidence: %s\n' "$evidence"
TXING_AGENT_TEMPLATE_ROLLOUT
then
  printf 'Update command finished successfully.\n'
else
  printf 'Update command stopped; keep launches disabled and share the error above.\n' >&2
fi
```

Verify both gates remain false, the new parameter/env equal 3000, unchanged
released controller code hash and newly selected image, concurrency one,
controller minute repair enabled, witness independent minute watch enabled,
current real REDCON 4 and zero nonterminal VMs. Use a fresh stack read and
preserve every unrelated parameter during later operator changes. AWS update
failure is not permission to proceed.
The conditional child-shell wrapper keeps the operator's terminal open on
failure, including when the caller already has `set -e` enabled.

## Staged live execution

### Local ARM64 candidate — 2026-11-02

`just agent::release-package` completed through the existing Lima engine with
exit zero. Evidence: `tmp/agent-release-0.1.1.R6hwn6/` and
`tmp/issue-170/{release-package.log,arm64-candidate-verified.json}`.
The Linux ARM64 build passed all eight CTest targets, dynamic linking/startup
in the recorded `provided.al2023` digest, repeatable archives from one frozen
build, and the actual packaged runtime's help/ready checks without networking.
Ready reports no runtime identity, credentials or device sessions initialized.

The independently inspected ZIP has SHA-256
`050f90f05833f4a388888b7f0a41d2fc4393f06d8b5b5da9b951f66676860587`;
source build ID is
`ef2aed291deaf5bc5f387a36153ef3d0be86b05df4d39dbcb063c9fc4260c196`.
All outer/nested checksums, archived source hashes, embedded 0.1.1 version and
budget configuration, and actual AArch64 executable headers were verified.
It is explicitly `clean=false`, built from uncommitted changes over `8d7cd042`,
and exported under `tmp/agent-releases/candidates/0.1.1/`. It must not be
published. A clean committed GitHub build must supply the production artifact
and its own checked identities. Operator reports REDCON 4 and QGC started but
disconnected; secured/lifted/disarmed readiness and exact QGC setup must still
be confirmed before physical control.

### Clean immutable GitHub release — 2026-11-02

The operator pushed `main` at
`a05504aab5685dec40622a08cef1c32c97c2f7a7`. Its 325 build-input files exactly
match the locally validated candidate's manifest. Dispatched
[CI run 41415315670](https://github.com/mparkachov/txing/actions/runs/41415315670)
completed successfully: fifteen publication/failure/retry Python tests, eight
Linux ARM64 CTests, repeatable frozen-build packaging, controller linking/startup
and packaged runtime help/ready checks. The
[agent-v0.1.1 release](https://github.com/mparkachov/txing/releases/tag/agent-v0.1.1)
was published at 08:52:23 UTC / 09:52:23 CET.

| Identity | Verified value |
| --- | --- |
| Archive SHA-256 | `5756af87015e8859d3d765d13593fbcc27f0be7cb3c7b3bf1bfc1d19d2a8adfa` |
| Source build ID | `ef2aed291deaf5bc5f387a36153ef3d0be86b05df4d39dbcb063c9fc4260c196` |
| MicroVM ZIP SHA-256 | `81ea15d41bf77c96e34430b47e2d5c814143048321c03ee8fa3453cafb8c9cab` |
| Controller ZIP SHA-256 | `6d09d6b36dea04dd33a86dee89111d01d3c677265d0c41d7e9fd4d6e27ff000a` |
| Expected controller CodeSha256 | `bQnWs23qBN0zqG3uiREdAdPGdyZdDEHX6f1Nbif/AAo=` |
| Template SHA-256 | `a2e210bc896e006e0f25be7558759e5dd5ff6a15456e6451410d1b67f905c0e3` |

Downloaded release and CI evidence are under
`tmp/issue-170/release-0.1.1/`, including `verified-release-summary.json`.
The GitHub asset digest, CI-logged archive digest, actual tag/CI/source revision,
`clean=true`, all outer/nested ZIP and archived source hashes, source version/
budget configuration, and both actual AArch64 ELF binaries agree. Controller
runtime checks and packaged ready-without-initialization evidence also pass.
This release is distinct from the earlier dirty local candidate; do not use
the candidate's ZIP hashes for deployment.

The pre-publication AWS reads retained 0.1.0/image 3.0 with both launch gates
false and an empty dedicated-image inventory. Managed base catalog version `2`
was `AVAILABLE`; the operator publication command rechecks that state. The
GitHub build alone establishes no AWS publication, template update, activation
or physical acceptance. The following operator publication subsequently passed:

```sh
TXING_AGENT_BASE_IMAGE_VERSION=2 just agent::publish 0.1.1
```

### Operator AWS publication — 2026-11-02

The operator's final terminal result selected `agent-v0.1.1`, dedicated
`town-agent` image **4.0**, for later launches. Evidence:
`tmp/agent-publish-0.1.1.fW8rga/`. Independent checks of that evidence and fresh
read-only AWS responses confirm:

- The downloaded clean archive is byte-identical to the verified GitHub asset;
  all release file hashes and source/build identities match.
- Image 4.0 is `SUCCESSFUL`/`ACTIVE`, parent image `UPDATED`, from
  `s3://town-agent-artifacts-7huc6mggtip3/agent/0.1.1/microvm.zip`.
  The saved build input matches the returned settings, including managed base
  `2` reported as `2.0`. The immutable request token is
  `7759bc04eaa56c4a20d876562aa280878e5b6a5e6f749aacb30f13d0ae2864d2`.
- Successful receipt upload checksum matches its bytes; S3 receipt VersionId
  is `xCT2Ar2EUfzKcqWTzyA5MwssfLshlwm8`.
- Stack `town-agent` is `UPDATE_COMPLETE`, selecting release 0.1.1/image 4.0
  and `agent/0.1.1/controller.zip`. Both switches remain false and every other
  unrelated parameter is preserved. Stack LastUpdatedTime is 08:57:56.460 UTC
  / 09:57:56.460 CET; this is not an exact completion timestamp.
- The controller is `Active` with `Successful` last update; CodeSha256 matches
  the release's `bQnWs23qBN0zqG3uiREdAdPGdyZdDEHX6f1Nbif/AAo=`. Its environment
  selects release 0.1.1/image 4.0 with automation disabled. Its LastModified is
  08:58:09 UTC / 09:58:09 CET.
- Complete dedicated-image inventory is empty. No activation or physical
  acceptance is implied by publication.

Derived audit: `tmp/issue-170/release-0.1.1/verified-publication-summary.json`.
The newly released controller currently uses its missing-setting default 3000;
the old deployed template has no explicit budget parameter/environment entry.
A semantic comparison of the deployed original template and verified release
template confirms exactly two additions: `ActivationBudgetSeconds` and its
controller environment reference. No other resource/template changes occur.
The concrete reviewed parameter file preserves every previous parameter and
adds 3000. The operator command block is
`tmp/issue-170/release-0.1.1/template-update.md`; it checks the stack against the
reviewed state before updating and waits for completion. POSIX parsing and
ShellCheck pass. Keep REDCON 4 and QGC disconnected, with both launch gates
false. AWS mutations remain operator-run; this disabled template update is the
next gate before live enablement.

The first manual instruction block used top-level `set -e`; the operator
reported that the `cmp` step closed their terminal. The saved comparison files
are byte-identical, and a fresh stack read still matches the reviewed state;
there is no retained evidence of a comparison mismatch. At that checkpoint no
update-response file existed and the budget template remained uninstalled. The
revised block uses an explicit conditional child shell, compares parsed JSON with `jq`, and
prints progress/error details. It retains the state guard and both disabled
launch gates. Twelve local cases exercise the actual revised block under
parent `set -e` in both `sh` and `zsh`: success, mismatched state, failed read,
malformed JSON, rejected update and failed completion wait. The parent survives
every case, and a mismatch submits no update. All AWS calls in these checks are
mocked; this is shell-behavior validation, not an executed CloudFormation update.
Evidence: `tmp/issue-170/release-0.1.1/template-shell-regression-summary.json`.

### Disabled release-template update accepted — 2026-11-02

The operator ran the revised block and reported successful CloudFormation
completion. Its `template-after.json` and fresh read-only AWS responses confirm
`UPDATE_COMPLETE`, release 0.1.1/image 4.0, `ActivationBudgetSeconds=3000`, and
both launch switches false. The active/successfully updated controller retains
the exact published CodeSha256 and now explicitly receives budget `3000` in
its environment. The deployed original template is semantically identical to
the verified release template. Stack LastUpdatedTime is 09:41:42.816 UTC /
10:41:42.816 CET; controller LastModified is 09:41:49 UTC / 10:41:49 CET. Neither
timestamp is an exact end-to-end completion measurement.

Controller reserved concurrency is one; its minute repair and witness's
independent minute watch are enabled. Witness remains scoped to the same image.
The lifecycle IoT rule is disabled, dedicated-image inventory is empty, TBot is
born REDCON 4 with `capability.agent=false`, and its agent shadow is stopped
without run/endpoint. Prior activation identity/start/deadline are unchanged.
Registry inventory currently contains only one Thing declaring agent:
`tbot-8yzfgj`. Evidence and derived audit are under `tmp/issue-170/enablement/`,
including `verified-disabled-template-summary.json`.

The prepared `enable.md`/`enable-parameters.json` change only the two launch
switches to true, preserving the released artifacts, budget and other values.
The operator block checks both reviewed stack state and current inactive born
REDCON 4 first. A conditional child shell preserves the parent terminal.
Sixteen local `sh`/`zsh` cases verify that stack changes, active/dead/unverified
device evidence and shadow errors prevent submission, and update/wait failures
keep the parent open. Every AWS call in these checks is mocked. POSIX parsing
and ShellCheck pass; this is prepared enablement, not an executed AWS update.

Before physical control, obtain the operator's current secured/lifted/disarmed
and QGC-configuration confirmation. Keep REDCON 4/QGC disconnected during
enablement. Then verify that the enabled controller directly recorded a fresh
inactive observation before requesting normal activation. The retained old
activation or a merely enabled trigger does not establish that observation.

### Controlled enablement and fresh inactive observation — 2026-11-02

The operator completed `tmp/issue-170/enablement/enable.md`. Retained
`enable-after.json` and fresh AWS reads show `UPDATE_COMPLETE`, both launch
switches true, and every unrelated parameter preserved. Release 0.1.1/image 4.0,
budget 3000 and controller CodeSha256 remain unchanged. The controller is active
with successful last update and automation enabled; the lifecycle IoT rule is
enabled. Stack LastUpdatedTime is 10:03:26.599 UTC / 11:03:26.599 CET; controller
LastModified is 10:03:33 UTC / 11:03:33 CET.

Agent shadow version 131 records `controller.observed=true`, `active=false`,
projection version 1910 and its exact source timestamp. `inactiveObservedAt`
is **1793613909 = 10:05:09 UTC / 11:05:09 CET**, after enablement. This is a new
direct inactive observation, not merely the retained historical activation.
The agent remains stopped without run/endpoint, that old activation is unchanged,
and the dedicated-image inventory is empty at this checkpoint. Derived audit:
`tmp/issue-170/enablement/verified-enabled-inactive-summary.json`.

The operator explicitly answered **“Yes, setup confirmed”** to the current
secured/lifted/wheels-clear/initially-disarmed check and QGC v5.1.5 setup
(UDP listener 14550, remote 127.0.0.1:14551, heartbeats enabled). QGC remains
disconnected. Record: `physical-readiness-confirmed.json` in that directory.
Normal Office REDCON 1 activation was requested for the first released-system
unattached observation. No attach/control command is authorized by that step;
the next evidence must establish one released VM, increasing real telemetry and
encoded video, and no attachment/held control before continuing.

### Automatic released-system unattached observation — 2026-11-02

The operator reported actual REDCON 1 after normal Office activation, with QGC
disconnected and no attach command running. Read-only collection spans
10:09:09–10:11:32 UTC / 11:09:09–11:11:32 CET. It captures the stopped baseline,
then exactly one assigned released VM; later runtime log samples extend the
unattached observations to 10:12:24.847 UTC / 11:12:24.847 CET.

| Identity | Observed value |
| --- | --- |
| VM | `microvm-c01b6257-c852-36d9-9c47-cef9a732e73f`, image 4.0, `RUNNING` |
| Run | `92619073-20BB-46F5-891F-C023726E53F3`, release 0.1.1 |
| Activation | `CBD78DDE-3F6B-4804-A6B6-33B3C1346902` |
| Activation start/deadline | 1793614178 / 1793617178 (10:09:38 / 10:59:38 UTC, 11:09:38 / 11:59:38 CET) |
| Activation budget / AWS requested maximum | 3000 seconds / remaining 2996 seconds |
| AWS start | 10:09:42.730 UTC / 11:09:42.730 CET |
| Runtime source build | `ef2aed291deaf5bc5f387a36153ef3d0be86b05df4d39dbcb063c9fc4260c196` |

Twenty-seven parsed runtime log samples match this VM/run/activation/deadline
and release source build; all show `attached=false` and `controlHeld=false`.
After startup verification, both sessions are connected, authority checks are
fresh and telemetry/video counters increase. The last sample reports **2643
telemetry messages and 4607 encoded video frames** at uptime 156707 ms. Its last
H.264 frame has 29598 bytes, presentation timestamp 146225950000 in 100 ns units
and receipt Unix ms 1793614344821. These are real frames delivered to the
operator boundary, which counts/discards them; no QGC video-display claim is
made. Initial pre-verification samples have zero media, not an established
authority grant.

Every active-phase complete dedicated-image inventory contains exactly this one
nonterminal assigned VM. Run/activation/deadline and exact saved launch request
remain unchanged. AWS reports the fixed managed ingress/Internet egress
connectors and no idle policy. The fresh board sample has a ready link/fresh
heartbeat, disarmed state, two connected MAVLink peers and two observers, with
no held owner. Native attach baseline on macOS **27.2 (26B123)** has executable
SHA-256 `1264dcad353323e5d7f4240e09dc7a41187a8c6f81f8180f56bd60764e7eb714`;
linked libraries are recorded. QGC v5.1.5/settings are operator-confirmed.

Evidence: `tmp/issue-170/live-observation/`, including exact shadows/inventories/
VM responses, runtime log events and parsed samples, native identity, and
`verified-unattached-observation-summary.json`. This accepts bounded released
startup/receipt without a human attachment. It does not prove REDCON 2/1
independence, parameter/motion/contention/loss, accelerated expiry or final zero
compute; those remain pending. The earlier intermittent #167 timeout is not
established as repaired by this healthy bounded run.

The next requested command is
`just agent::attach tbot-8yzfgj --region eu-central-1`, followed by connecting the
existing QGC UDP link while remaining disarmed. Observe live telemetry and
unchanged cloud/board peer identities before explicit control/parameters. This
attachment is operator-run because obtaining its AWS token is an AWS mutation;
no token/attachment or device action was executed by the implementing agent.

### Observation attachment and explicit parameter control — 2026-11-02

The operator ran the observation attachment and reported its loopback
14551→14550 mapping and `telemetry connection=2 cloud agent telemetry`. Runtime
logs show an authenticated attachment on the same released VM with no held
control, increasing real streams and unchanged run/activation/deadline. Board
peers remain two connected/two observers. QGC's parameter list initially waits:
observation mode blocks its uplink parameter requests. That expected write gate
is not accepted as parameter retrieval or recorded as a transport failure.

After ending that observation attachment, the operator started
`just agent::attach tbot-8yzfgj 14551 --control --region eu-central-1` and
reconnected QGC. The terminal reports `control=1 cloud agent control state` and
the operator confirms parameters loaded after the requested Refresh. Board
shadow 1341 confirms QGroundControl session `mavlink-2`, epoch 1, 5000 ms lease,
disarmed and two connected/one observer peers. Real runtime status confirms
attached/held/fresh-assignment true, both streams connected and unchanged
released VM/run/activation/deadline. Evidence:
`tmp/issue-170/{attach-observer,parameter-control}/`.

### Released secured/lifted QGC manual flow accepted — 2026-11-02

Using that same attachment, the operator reports actual wheel motion and the
complete normal arm → brief drive → neutral/stop → disarm → re-arm → final
disarm sequence succeeded. Forty read-only board samples capture:

| Shadow version | Armed state | First capture UTC / CET | Control owner |
| --- | --- | --- | --- |
| 1341 | false | 10:23:13 / 11:23:13 | QGroundControl, mavlink-2, epoch 1 |
| 1342 | true | 10:23:34 / 11:23:34 | Same session/epoch |
| 1343 | false | 10:24:06 / 11:24:06 | Same session/epoch |
| 1344 | true | 10:24:24 / 11:24:24 | Same session/epoch |
| 1345 | false | 10:24:40 / 11:24:40 | Same session/epoch |

All sampled held leases retain the same owner/epoch/TTL; thirteen runtime
samples during the physical arm-cycle interval retain held control, attachment
and fresh assignment. Run/release/activation/deadline are unchanged. This
establishes session-owned control across disarm/re-arm rather than tying the
lease to arm state. The operator's reported motion and stop complement board
state; a shadow alone cannot establish actual wheel movement.

After the final disarm, the attachment closes and board shadow 1347 is unowned,
disarmed, Hold, with two observers at 10:24:56 UTC / 11:24:56 CET. The later
runtime sample is detached/control-lost (`operator released`) while both streams
continue on the same VM. The terminal cause of closure was not supplied, so no
specific client-cutoff or AWS server-token-expiry claim is made. This completes
the issue's localhost attachment/parameter/secured physical-flow criterion.

Evidence: `tmp/issue-170/physical-control/`, including raw shadows with metadata,
runtime events/samples and `verified-physical-flow-summary.json`. Contention,
client/transport/lease/lifecycle faults, duration boundary and final zero compute
remain open; this bounded pass does not establish repair of the historical #167
intermittent timeout.

The first client-loss answer was submitted before the operator finished the
test, then explicitly withdrawn for a repeat. Its 25 captured board samples
contain no held lease, so they cannot establish held-control release. Preserve
`tmp/issue-170/client-loss/` as inconclusive. A fresh explicit grant and timed
QGC-only disconnect/reconnect are requested, with separate evidence under
`tmp/issue-170/client-loss-repeat/`; no client-loss pass is claimed yet.

### Repeated QGC client-inactivity release — 2026-11-02

The operator requested a repeat after submitting the first answer too early.
Fresh evidence under `tmp/issue-170/client-loss-repeat/` captures a new explicit
free-lease grant: board shadow 1348, QGroundControl/mavlink-2/**epoch 2**, disarmed,
two peers/one observer. The requested case disconnects only QGC's UDP link while
keeping the native attachment open, then reconnects and waits. The operator's
terminal reports:

```text
control=1 cloud agent control state
QGroundControl: client inactive for 5 seconds; control requires a new --control run
control=0 cloud agent control state
```

Board shadow 1349 removes the owner and reports disarmed/Hold with two observers.
Twenty-five later board samples retain no owner. Eighteen post-loss runtime
samples over **90.271 seconds** retain `attached=true`, `controlHeld=false`, lost
control with `client inactivity or lease expiry`, fresh assignment and both
connected/increasing streams. No new grant appears after the requested QGC
reconnect; VM/run/activation/deadline remain unchanged. This distinguishes the
case from closing the WebSocket. The precise UI disconnect click timestamp was
not retained, so the native five-second diagnostic is recorded without claiming
an exact measured end-to-end latency.

Derived audit: `verified-client-loss-summary.json` in that directory. The first
`client-loss/` capture remains inconclusive; it is not replaced or counted as a
pass. This accepts the repeated client-inactivity release/no-observed-regrant
case, not all contention/transport/lease/lifecycle-evidence-loss requirements.

### Office busy rejection and explicit takeover — 2026-11-02

In the Office-first case, board shadow 1351 records Office/mavlink-1/epoch 3.
The attached cloud operator remains an observer with `control_busy`; the
operator reports `control=0` and unavailable QGC parameter loading. The agent
does not take Office's lease. An earlier capture window missed the Office
action; later direct board/runtime evidence establishes the actual contention.
After Office release, shadow 1353 is unowned/disarmed/Hold. The native
attachment subsequently reports its token-lifetime cutoff, so that episode
alone does not prove the requested fifteen-second post-release window.

The first instruction incorrectly described Office acquisition as disarmed.
Office's existing Control action selects Manual and sends an ordinary Arm.
The instruction was corrected, the operator was immediately asked to release,
and the secured/lifted device returned to disarmed/Hold. The
[board contract](contracts/board-mavlink.md) now states this existing Office
behavior explicitly. This was an instruction error, not an unexpected agent
takeover or an operator error.

A fresh explicit QGC attachment then obtains epoch 4 (board 1354, disarmed).
With the operator informed that Office acquisition arms and all inputs neutral,
Office explicitly takes epoch 5 (board 1356, Manual/armed). QGC reports
`control=1` then `control=0`; runtime records `stale_epoch`. Office release
leaves board 1358 unowned/disarmed/Hold. Fifty later board samples retain that
state. Runtime remains attached without held control or automatic regrant for
**195.581 seconds**, with both streams healthy and the same VM/run/activation/
deadline. The operator confirms Office has no control and QGC is disarmed.

Evidence: `tmp/issue-170/{office-contention,office-release,office-takeover}/`,
including `office-takeover/verified-office-contention-summary.json`. This accepts
busy rejection and explicit takeover/lease-loss subcases; other transport,
attachment and lifecycle-verification losses remain separate requirements.

### Actual fifty-minute expiry and no observed rollover — 2026-11-02

Activation `CBD78DDE-3F6B-4804-A6B6-33B3C1346902` retains its original
1793614178–1793617178 allowance (11:09:38–11:59:38 CET). AWS records VM
`microvm-c01b6257-c852-36d9-9c47-cef9a732e73f` **TERMINATED** at
11:59:44.757 CET, reason `MicroVM exceeded maximum lifetime.` Its requested
remaining hosting duration was 2996 seconds; actual VM lifetime is
**3002.027 seconds**, with terminal state **6.757 seconds after** the absolute
activation deadline. This is measured hosting cleanup, not evidence that live
control authority extended beyond the deadline or that compute stopped exactly
at it.

Twenty-two snapshots retain born REDCON 1. Agent shadow versions 254–256 are
expired without run/endpoint and preserve the original activation/start/deadline.
Complete image inventories have zero nonterminal VMs through 12:02:57 CET,
covering at least two later minute repair passes. No automatic rollover is
observed in that continuously active window. Evidence:
`tmp/issue-170/full-budget-expiry/verified-full-budget-summary.json` and raw
captures. The explicit accelerated replacement/reactivation criterion remains
open.

The requested expired-attachment negative check was not performed against that
expired state: the operator reported cycling REDCON 4→1 first. The subsequent
successful observation attachment belongs to permitted activation
`89D09D21-EB20-4A44-9755-E4DADD4763B5`, not the old run. Its VM
`microvm-7b7cd447-d675-34f5-b161-392d06f764da` also ultimately terminates for
maximum lifetime at 12:54:48.820 CET; it is not counted as REDCON 4 shutdown.
Do not count this attachment as either stale-endpoint failure or a negative
test pass.

Later actual REDCON 4 ends VM
`microvm-51c5661d-07ce-340a-884b-d726f4b7944c` at 14:10:36.309 CET with
service reason `Success.` Fresh projection 1929 is born REDCON 4,
`capability.agent=false`; the controller observes inactive and clears run and
endpoint. All three image VMs are terminal. The operator then installs
`ActivationBudgetSeconds=600` while inactive. Fresh read-only verification at
13:22:10 UTC / 14:22:10 CET confirms UPDATE_COMPLETE, unchanged release 0.1.1/
image 4.0/controller checksum and unrelated parameters, controller environment
600, and a directly observed inactive record after the controller update.
The retained activation history is unchanged and the inventory has zero
nonterminal VMs. Evidence: `tmp/issue-170/accelerated-budget/`, including
`verified-budget-600-summary.json` and `latest-pre-inactive-vm.json`.

### Accelerated replacement and duplicate hints — 2026-11-02

Normal activation reaches actual REDCON 1 with QGC disconnected and a freshly
disarmed/unowned board. Activation `85B47983-D905-4299-97C3-69ABB6B203D5`
retains start 1793625834 and deadline 1793626434: exactly **600 seconds**,
ending **14:33:54 CET**. Initial run `C814AA5D-426F-47B1-B2A6-6E05DB51E9CE`
uses VM `microvm-d9106e8d-4fdd-3abe-878c-ef470c739a77`, started
14:24:02.834 CET with a remaining hosting maximum of **592 seconds**. Real
telemetry/video connect without attachment or control.

The operator runs the guarded `accelerated-budget/replace.md` command while
leaving actual REDCON 1 unchanged. AWS records the exact original VM terminal
at **14:26:16.532 CET**, reason `Success.` The controller clears that run and
automatically starts `D2FA2880-23C3-4DA5-80ED-05A3827A143E`, VM
`microvm-a52472b7-52df-3f9f-931d-b4508d08b504`, at **14:28:09.641 CET**.
Its hosting maximum is only **345 seconds**. Activation identity/start/deadline
are identical; the new run/endpoint do not reset the allowance. Both actual
streams recover with the exact released build identity, fresh assignment,
no attachment and no held control. Derived audits:
`verified-accelerated-initial-summary.json` and
`verified-accelerated-replacement-summary.json` under
`tmp/issue-170/accelerated-budget/`.

At **13:30:31 UTC / 14:30:31 CET**, the operator begins three synchronous
invocations of the released controller with the same derived old lifecycle
hint, `{"thingName":"tbot-8yzfgj"}`. This is the actual rule's selected payload
for both earlier and current projected updates; no authoritative shadow is
replayed or changed by the test. Each invocation returns 200 without
FunctionError. Before/after activation, run and endpoint are identical, and
the complete image inventory has exactly the assigned replacement as its one
nonterminal VM. Evidence: `accelerated-budget/events-active/`, including
`verified-active-event-replay-summary.json`. This bounded active replay does not
by itself accept expired-state replay or stale endpoint fencing.

The replacement reaches AWS **TERMINATED** at **14:33:56.594 CET**, reason
`MicroVM exceeded maximum lifetime.` Actual replacement VM lifetime is
346.953 seconds, **2.594 seconds after** the absolute activation deadline.
This measured hosting grace is distinct from runtime authority timing. The
last parsed runtime sample is at 13:33:52.214 UTC, before the deadline, with
fresh assignment, no attachment/control, both streams healthy and increasing.
No final runtime stop sample was retained by the five-second status logger;
that logger alone cannot establish an exact live authority cutoff timestamp.

Sixty-two snapshots of this activation retain its original identity/start/
deadline with at most one nonterminal VM. Actual REDCON values are 2 during
startup and then 1, continuously active without an inactive interval. Twelve
expired-state snapshots contain no run/endpoint and zero nonterminal VMs,
through **13:36:32 UTC / 14:36:32 CET**, **158 seconds after** expiry, including
later minute repair passes. The shadow versions are 530, 531, 532, 534 and 535;
no automatic rollover is observed. Audit:
`accelerated-budget/verified-accelerated-expiry-summary.json`, with the complete
sample index and raw captures.

While the device remains at actual REDCON 1, the operator replays the same
old hint three more times starting **13:35:53 UTC**. All invocations succeed;
the expired activation stays unchanged without run/endpoint, and all image VMs
remain terminal. The subsequent real observation attachment builds successfully
and refuses with exit 1: `agent attach: no verified current cloud assignment`.
This is the accepted expired-state negative check; no REDCON cycle intervenes.
Evidence: `accelerated-budget/events-expired/`, especially
`verified-expired-replay-and-refusal-summary.json`. This checks current
assignment refusal, not a separate authenticated request to the former URL.

The operator subsequently sets actual REDCON 4 and completes the guarded
`restore-budget-3000.md` update. Fresh inspection at **13:47:48 UTC /
14:47:48 CET** confirms UPDATE_COMPLETE, normal budget/environment 3000,
unchanged release 0.1.1/image 4.0/controller checksum and unrelated parameters.
The controller records inactivity at 1793627229 (after its 13:46:53 UTC update),
with no run/endpoint and the expired 600-second activation history preserved.
Sparkplug version 1938 is actual REDCON 4; complete image inventory has all five
VMs terminal. Audit: `accelerated-budget/verified-restored-budget-summary.json`.

The operator then activates normally once through Office, keeping QGC
disconnected and the secured/lifted TBot disarmed. Actual REDCON 1 is reported
by the operator and fresh projection 1943. The controller creates new
activation **8E235204-AC0F-46AA-80D8-4F929428573D**, start 1793627382 and
deadline 1793630382: **3000 seconds**, ending **15:39:42 CET**. New run
`4B8F3611-CCC8-4AC1-A959-1CF0AA87CB08` uses released image 4.0 VM
`microvm-84c41de6-e5d2-34be-b4e5-e6dad1b5f561`, started 14:49:46.820 CET,
with a remaining hosting maximum of **2996 seconds**. Board 1389 is freshly
disarmed with two observer peers and no owner. Eight parsed runtime samples
match the exact released build and new identities; the last at
13:50:23.223 UTC has fresh assignment, no attachment/control, connected streams,
553 MAVLink messages and 940 actual H.264 frames (last frame 21420 bytes).
Evidence: `tmp/issue-170/post-budget-reactivation/`, including
`verified-fresh-reactivation-summary.json` and initial raw/runtime captures.

This completes the combined accelerated-duration criterion: replacement uses
only remaining time, continuous activity and replayed hints do not roll over,
expired attachment is refused, and a directly observed inactive→active
transition permits a new allowance under the restored normal budget. Both
launch switches stay enabled for the remaining controlled physical cases and
will be disabled at final closeout. No shadow is reset to manufacture time.

### Explicit attachment closure releases control — 2026-11-02

The operator starts a new explicit `--control` attachment on that fresh normal
activation, connects QGC, waits through the requested twenty-second held
baseline, then presses Ctrl+C only in the attach terminal while leaving QGC's
UDP link connected for another twenty seconds. Terminal output records:

```text
control=1 cloud agent control state
^Ccontrol=0 attachment closed
error: interrupted by SIGINT
```

The SIGINT is the requested operator termination. QGC reports communication
loss because its localhost attachment has closed; the cloud agent continues
observing. Board version 1390 holds QGroundControl/mavlink-2/epoch 1, TTL
5000 ms, while disarmed. Version 1392 is unowned/disarmed/Hold with two observer
peers; thirty-five later captured board samples retain no owner. Six runtime
samples capture held control. Nine post-detach runtime samples over **45.129
seconds** are detached/control-lost (`operator released`) without regrant,
with fresh assignment and both connected/increasing real streams. VM/run/
activation/deadline are unchanged. The exact Ctrl+C click timestamp is absent,
so this establishes actual release and observation continuity without an exact
click-to-release latency claim.

Evidence: `tmp/issue-170/post-budget-reactivation/`, especially
`verified-attachment-loss-summary.json`, `attachment-loss-runtime-samples.json`
and `capture/`. The operator was then asked to disconnect QGC and run a
read-only board transport preflight before any network fault. No transport-loss
or unavailable-evidence pass is inferred from closing the local attachment.

### Board transport preflight and prepared UDP fault — 2026-11-02

The operator's read-only SSH preflight at **14:29:19 UTC / 15:29:19 CET**
identifies hostname `tbot`, kernel **6.18.58-0-rpi**, boot
`aba35909-cfc5-4d90-93d4-9bd1cc8c4438`, uptime forty minutes and default route
through `wlan0`. All four board services report started. Actual running files:

| Component | Installed/running identity | Actual executable SHA-256 |
| --- | --- | --- |
| Daemon | txing-tbot-daemon 0.18.12, PID 2637 | `5452ca53b2e024a06d1197660fe47888aa29f12575344129a44e13d612da5a47` |
| KVS master | txing-board-kvs-master 0.18.6, PID 2656 | `050ca5811304dbd643893cc30080c9703e82c833d2c027f627177d167147f8e7` |

`iptables` is unavailable; no `nft` result is present. Existing `tc` is
iproute2-v7.0.0. The only wlan0 qdisc is its `pfifo_fast` root; no egress
filter is reported. Fresh needed AWS reads still show actual REDCON 1,
disarmed/unowned board 1398, both cloud streams connected and the same single
released VM/run/activation/deadline. Evidence:
`tmp/issue-170/transport-preflight/board-preflight.txt` and `current-*.json`.

Prepared `tmp/issue-170/udp-loss.md` for manual operator execution: a fresh
disarmed QGC grant and twenty-second baseline, then temporary IPv4/IPv6
outbound UDP-drop filters on a new clsact qdisc for approximately 25 seconds,
recorded packet counters, restoration and sixty seconds without reacquisition.
TCP traffic and the existing root qdisc are preserved; UDP DNS/NTP is briefly
affected. Live evidence must establish whether the actual WebRTC data path is
lost and whether authoritative lifecycle stays active. This affects both media
paths and cannot substitute for the separate independent-media case.

The block guards the exact current run/activation, three minutes of remaining
allowance, actual REDCON 1, a disarmed QGC lease, the reviewed board boot and
unchanged root qdisc. Partial failure/exit/signal restoration and an exact
manual recovery command are included. POSIX parsing/ShellCheck pass. Eight
local mocked command-path checks pass (normal restoration, changed boot/root
qdisc, qdisc-add rejection, either filter-add failure, interruption and explicit
restoration failure). Evidence: `tmp/issue-170/udp-loss-mock-checks/summary.json`.
Those checks mutate no networking and do not prove board kernel support or
released-cloud fault acceptance. No live fault or recovery pass is claimed at
this checkpoint. A time-guard refusal means the fault was not applied.

The remaining-time guard subsequently closes before any board fault log is
present. The operator request is superseded: stop any attachment, disconnect
QGC and set actual REDCON 4. A fresh inactive/terminal observation must precede
the next activation, after which the exact identities and board boot guard will
be refreshed. Do not execute the old block against a different run. No live
transport outcome is accepted from this prepared attempt; retain any subsequent
operator output for classification. Record:
`tmp/issue-170/udp-loss/superseded-time-window.json`.

The operator confirms actual REDCON 4 for the superseding instruction. Fresh
projection **1946** reports REDCON 4/agent unavailable, source timestamp
1793630354336; the controller directly observes inactive at **1793630362**,
clears run/endpoint and preserves activation history. AWS records the reviewed
VM `microvm-84c41de6-e5d2-34be-b4e5-e6dad1b5f561` **TERMINATED** at
**15:39:16.111 CET**, reason `Success.`, **25.889 seconds before** its budget
deadline. The complete image inventory contains six terminal VMs and zero
nonterminal states. This is actual REDCON 4 shutdown evidence; it is not a
transport fault or a claim that the budget backstop caused termination.
Audit: `udp-loss/verified-inactive-shutdown-summary.json`. The read-only capture
ends successfully after seventy samples. REDCON 3/death cases remain open.

A fresh normal activation and repeat read-only board preflight are requested
next, with QGC disconnected and the TBot disarmed. The superseded fault block
is visibly marked unusable until its exact run/deadline/boot guards are
refreshed. No fault is applied merely to fill an expiring observation window.

The operator completes that fresh activation and read-only preflight at
**14:42:06 UTC / 15:42:06 CET**. Boot identity is now
`d9c7098a-88bb-4c57-8159-13c4090a5460`; the same daemon/KVS versions and
executable hashes are running (PIDs 2635/2654), with the same kernel, wlan0
route and unchanged pfifo_fast root. All four services are started. Fresh AWS
reads verify release 0.1.1/image 4.0/controller checksum, enabled automation
and budget 3000. Activation `D1F3AB16-957B-4D75-A5B2-9C2C22D195C4` retains
1793630512–1793633512, ending **16:31:52 CET**. Run
`667AC917-9845-42B6-B603-E7A4F7F3ED54` uses VM
`microvm-c810a212-3b84-3212-b655-2b7abfd12bc9`, started 15:41:56.815 CET
with 2996 seconds of remaining hosting time. Board 1404 is disarmed/unowned;
both real streams connect and exactly this one VM is nonterminal.

Evidence: `tmp/issue-170/transport-preflight-repeat/` and
`udp-loss-repeat/verified-fresh-baseline-summary.json`. The new
`tmp/issue-170/udp-loss-repeat.md` changes only the reviewed identities,
deadline and evidence path; its executable command logic is checked equal to
the previously validated block after reversing those substitutions. POSIX
parsing/ShellCheck pass. The operator is asked to use only this fresh block for
the twenty-second held-control baseline, bounded UDP fault and sixty-second
recovery observation. New read-only capture is under `udp-loss-repeat/capture/`.
The transport-loss outcome was pending at that preparation checkpoint.

### Real UDP transport loss, release and recovery — 2026-11-02

The operator runs the fresh guarded block. Board 1405 and runtime logs first
establish a disarmed QGroundControl/mavlink-2/epoch 1 lease, TTL 5000 ms.
The actual filters run from **14:45:47 to 14:46:12 UTC** (15:45:47–15:46:12
CET). Board monotonic uptime changes 289.38→314.47: **25.09 seconds** including
setup/statistics/restoration. Kernel counters record **21,933 IPv4 UDP packets**
and **5,567 IPv6 UDP packets** dropped. The new clsact and both filters are
removed successfully; the original pfifo_fast root remains. No package or
service change occurs in this case.

The first parsed lost-control runtime sample at **14:45:53.817 UTC** remains
attached with fresh assignment and `control request timed out`. At
**14:46:03.847 UTC**, MAVLink is recovering with its independent
`no MAVLink telemetry for 15 seconds` diagnostic. The terminal reports
`control=1` then `control=0`, and telemetry states **2→1→0→1→2**. Board
versions 1406, 1408–1411 have no owner; fifty-nine post-loss board samples
remain unowned/disarmed, ending in Hold with two observers. All complete
inventories retain exactly the same one assigned VM. Every captured actual
lifecycle stays REDCON 1, with the same run/activation/deadline; parsed runtime
samples retain fresh assignment throughout the fault.

The first parsed runtime sample with recovered/increasing MAVLink is
**14:46:38.949 UTC**. Video remains nominally connected while its actual frame
counter stalls at 6658 during the outage; it is not described as continuously
healthy receipt. A later controller sample contains new encoded frames, and
the first subsequent parsed stderr sample with an increased video count is
**14:47:19.064 UTC**. These are observation bounds with log-sampling gaps,
not precise recovery latencies. The fault deliberately affects both media
paths and does not complete the separate video-only isolation requirement.

After loss the runtime remains attached without held control or a new grant
for **145.418 observed seconds**, through 14:48:19.235 UTC, over two minutes
after network restoration. The operator subsequently reports
`control=0 attachment closed` and `attachment token lifetime ended; start a new
explicit attachment`. This is the documented native attachment cutoff, not
demonstrated AWS server-token expiry and not a reported Ctrl+C closure. The
latest runtime is detached/lost with both actual streams increasing. The
eighty-one-sample capture finishes successfully, with no automatic reacquisition
or replacement observed.

Evidence: `tmp/issue-170/udp-loss-repeat/`, especially `board-fault.txt`,
`verified-udp-loss-summary.json`, `verified-capture-index.json`, raw captures
and `runtime-{events,samples}-final.json`. This accepts real UDP data-path loss,
lease release, peer recovery and no observed regrant. Lifecycle-evidence loss,
independent video behavior and remaining shutdown conditions stay open.

The next prepared case is `tmp/issue-170/redcon-3.md`: a new explicit disarmed
lease baseline, then manual stop of only `txing-tbot-mavlink`. Its reviewed
service-start restoration is included before execution; the operator leaves
the service stopped until actual REDCON 3, controller inactivity and terminal
compute are inspected. No stale/unavailable FC arm field after service loss is
accepted as fresh physical confirmation. This case remains pending.

### Actual REDCON 3, attachment closure and terminal compute — 2026-11-02

The operator establishes a fresh disarmed QGC lease. The guarded pre-fault
board shadow **1412** has a fresh FC heartbeat and QGroundControl/mavlink-4/
**epoch 2**, TTL 5000 ms; four parsed runtime samples hold control. The manual
service stop begins **14:58:20 UTC** and returns stopped at **14:58:21 UTC**.
Office reports actual REDCON 3. Fresh projection **1953** independently confirms
born REDCON 3 with power/board true, MAVLink/agent/video false. This is real
derived unavailability with the prior command target still 1, not a fabricated
projection or merely a requested level.

The native terminal reports `control=1`, then `control=0 attachment closed`,
followed by `attachment lost or authentication failed; control requires a new
explicit attachment` and exit 1. The actual lifecycle/VM evidence supports the
expected shutdown interpretation of that generic diagnostic. No automatic new
attachment/grant is observed.

AWS records `microvm-c810a212-3b84-3212-b655-2b7abfd12bc9` **TERMINATED** at
**15:58:24.422 CET**, reason `Success.`, **2007.578 seconds before** the saved
activation deadline. The controller directly observes inactive at
**1793631549**, retains activation history and clears run/endpoint. Complete
image inventory contains seven terminal VMs and zero nonterminal states.
Board 1416 reports the FC service unavailable, no fresh heartbeat and zero
peers; its unavailable `armed=false` field is not used as fresh FC safety
confirmation. The pre-fault fresh disarmed state and a post-restoration FC
check are kept separate.

Evidence: `tmp/issue-170/redcon-3/`, including
`verified-redcon-3-shutdown-summary.json`, `board-stop.txt`, pre/post raw
shadows, VM/inventory responses and runtime samples. This accepts actual
REDCON 3 shutdown as a separate subcase; device death and final disabled
inventory/cost review remain open. After verification, the operator is asked
to run only the already reviewed MAVLink service-start restoration with QGC
disconnected, then report actual lifecycle. No new attachment/control is
requested during restoration.

### MAVLink service restoration and verification-loss package — 2026-11-02

The operator starts `txing-tbot-mavlink` at **15:07:11 UTC / 16:07:11 CET**
and reports Office actual REDCON 1. Fresh board **1424** has a ready FC link,
fresh heartbeat, Disarmed/Hold and two observer peers with no owner. Projection
**1954** confirms actual REDCON 1. The controller creates new activation
`742A0EFC-804B-4B9A-91A8-655FD3E52EC7`, 1793632029–1793635029 (3000
seconds), ending **16:57:09 CET**. Run
`81EB9A7F-3A3B-464B-91A4-A337760793D0` uses image 4.0 VM
`microvm-7ab513c8-000e-3d09-ad77-7ef87b0705f2`, started 16:07:24.792 CET
with a remaining hosting maximum of **2985 seconds**. The start uses the
conservative prior inactive observation. The old run/endpoint are not revived.

The first controller response has a startup `runtime status sampling failed`
diagnostic. A later fresh read clears it on the same run and reports connected
MAVLink/video, with actual frame receipt increasing; no replacement or release
change is needed. Audit: `tmp/issue-170/redcon-3/verified-restoration-summary.json`
and raw restoration/checkpoint/runtime evidence. The restored FC state is
fresh evidence, distinct from the unavailable arm field during the fault.

Prepared the next manual package under `tmp/issue-170/unavailable-evidence/`.
The original `run.md` attempted to deny `iot:GetThingShadow` on TBot's bare
Thing ARN for the freshly resolved agent execution role. Its assumption that
this also matched named shadows was incorrect; the November 3 attempt and
correction below preserve the actual result.
Controller/witness/rig/board/operator roles and shadow contents are unchanged.
The block requires a new disarmed held-control baseline and exact current
run/activation, role identity, scoped document, absent test-policy name and ten
minutes of remaining budget. Only the operator performs token/policy mutations.

The local acceptance probe uses a private five-minute/8081-only token to sample
status approximately every 250 ms. It records the last verified age and first
unverified age using runtime uptime rather than cross-host wall-clock estimates.
After authority, attachment and held control are false, it attempts only a
WebSocket handshake to the old endpoint, sending no control/actuator message.
The test policy is removed after the bounded observation or through guarded
exit/signal restoration; only an exact matching test document can be deleted.
The operator reviews an explicit recovery block before execution. Tokens are
not printed or included in evidence summaries.

POSIX parsing/ShellCheck, four probe checks (including five handshake outcomes)
and nine local mocked policy-restoration/error paths pass. The latter cover
existing absence, changed document, get/delete denial, ambiguous deletion,
interruption and a failed put with no policy created. They call no real AWS
mutation and do not establish live acceptance. Prepared files include
`deny-tbot-shadow-reads.json`, `reviewed-status-config.json`,
`test_authority_probe.py`, `probe-checks.log` and
`policy-restore-mock-checks/summary.json`. The operator has been asked to run
this package and share the actual result; verification-loss/stale-endpoint
acceptance remains pending.

### Verification-loss preflight refusal and refreshed review — 2026-11-03

The operator reports that `attempt.9KXCDg` stopped. Its only execution evidence
is the three preflight shadow reads: the procedure still expected the November
2 run `81EB9A7F-3A3B-464B-91A4-A337760793D0`, but the current run is
`FBF74329-E3EC-4448-991B-1565BAA28045`. The exact-identity guard exits before
role lookup, test-token creation or IAM policy submission. This is an
unexercised case, not a runtime verification-loss failure. The original
procedure/config are archived with that attempt. Fresh read-only IAM inspection
resolves the execution role from CloudFormation, lists only
`ObserveAndVerifyAssignments`, and returns `NoSuchEntity` for the test policy.
No policy removal is needed.

Fresh projection **1962** reports actual REDCON 1/agent available. The released
0.1.1/image 4.0 controller has its unchanged checksum, both launch gates true
and budget 3000. Current activation
`DF9EFB45-B801-4424-A375-240C72AD69A6` is 1793693494–1793696494, exactly
3000 seconds, ending **2026-11-03 10:01:34 CET**. The sole nonterminal VM is
`microvm-540672e3-150f-3d19-8fe3-96abfdbe6464`, started **09:11:40.806 CET**
with hosting maximum 2994 seconds. All eight older listed VMs are terminal.
Board **1437** reports a fresh heartbeat, Disarmed/Hold, two observers and no
owner. Runtime evidence matches the released build and current identities,
reports no attachment/held control after operator release, and shows increasing
MAVLink and actual encoded-video receipt. This checkpoint does not establish
intermediate overnight lifecycle transitions.

The same operator procedure now uses a refreshed, frozen
`reviewed-status-config.json` for run/VM/activation/deadline checks. It never
adopts a different run automatically. Identity/budget, actual lifecycle and
fresh disarmed QGC-lease refusals now print explicit reasons before any test
token or policy submission. Twelve checks execute those extracted guards,
including the exact 600/601-second boundary, changed identity, inactive/unverified
authority, unavailable capability, armed/stale FC and absent/short lease. They
make no AWS calls. POSIX parsing, ShellCheck and the four existing probe checks
pass. Policy scope, bounded restoration and stale-handshake behavior are
unchanged. Verification loss and stale-ingress refusal remain unaccepted until
a real operator-run fault supplies the matching evidence.

Evidence: `tmp/issue-170/unavailable-evidence/attempt.9KXCDg/verified-preflight-refusal-summary.json`,
`checkpoint-20261103/`, `preflight-guard-checks.json` and the refreshed `run.md`.
Retry requires a new explicit Disarmed control attachment under the reviewed
physical setup, then the complete operator block. No production artifact,
deployed configuration or policy has been changed by the implementing agent.

### Ineffective verification fault; named-shadow resources corrected — 2026-11-03

The operator runs the fault and returns `attempt.kTKLIJ`. The authenticated
baseline is valid and held. The test policy is submitted at **08:25:41 UTC**
and removed/confirmed absent at **08:27:22 UTC**. All **295** authenticated
status samples over **99.743 seconds** return HTTP 200 with assignment verified,
attachment present and control held. Verification ages range **12–2009 ms**,
with approximately fifty new verification timestamps observed. The source
poller updates that timestamp only after successful lifecycle/assignment reads.
There is no captured `GetThingShadow` denial or unverified transition, and the
probe correctly reports failure instead of attempting or claiming stale-ingress
refusal. This does not establish a runtime failure to stop on unavailable
evidence: the intended evidence loss was never produced.

The prepared fault used the wrong resource. Named shadows require
`thing/tbot-8yzfgj/sparkplug` and `thing/tbot-8yzfgj/agent`; the bare Thing ARN
does not match either. This boundary was already documented in the earlier
[MicroVM permission finding](agent-microvm-acceptance.md#correct-the-named-shadow-permission-before-retrying)
and is confirmed by the current
[AWS action-resource reference](https://docs.aws.amazon.com/iot/latest/developerguide/iot-action-resources.html).
The mistake is in the acceptance procedure prepared by the implementing agent.

Fresh read-only IAM inspection confirms only the ordinary policy remains and
the temporary-policy lookup returns `NoSuchEntity`. Read-only AWS IAM custom
policy simulation combines the actual deployed allow policy with each denial:
the submitted bare-Thing denial leaves both named-shadow reads **allowed**;
the corrected two-resource denial makes both **explicitDeny**. The corrected
denial leaves the classic shadow, another named shadow and another Thing
unchanged; tested shadow writes remain denied. These are per-resource results,
not the simulator's aggregate decision. No simulation modifies IAM or proves
live propagation.

The same released run/activation/deadline remain, actual REDCON stays 1, and
both real streams continue. Later board **1439** has a fresh heartbeat,
Disarmed/Hold and no owner; the controller reports control lost with `operator
released`. That later release is not attributed to the ineffective IAM fault.
No replacement or authority-cutoff latency is claimed. The native terminal
messages have not yet been supplied for this attempt.

Corrected `deny-tbot-shadow-reads.json` and the procedure's exact-document
guard/recovery review target only those two named shadows. The actual submitted
document, procedure and configuration are archived inside the attempt. Six
checks execute the extracted restoration function with matching, old
bare-Thing, changed-resource, absent, read-denied and delete-denied documents;
only the exact matching document permits deletion. No AWS mutation occurs in
these checks. POSIX parsing, ShellCheck and the four existing probe checks pass.
No production code/image or deployed policy/configuration was changed by the
implementing agent. Retry remains operator-run and requires a new explicit
Disarmed control baseline; this acceptance criterion remains open.

Evidence: `tmp/issue-170/unavailable-evidence/attempt.kTKLIJ/verified-ineffective-fault-summary.json`,
its `post-check/policy-simulation-verified.json`, `capture-observations.json`,
raw samples and restoration evidence, plus `named-shadow-restore-checks.json`.

### Corrected shadow denial still produces no observed verification loss — 2026-11-03

The operator returns `attempt.8nRp9F` after applying the corrected exact
`sparkplug`/`agent` denial. The valid held-control baseline is followed by
submission at **08:36:41 UTC** and removal/confirmed absence at **08:38:22
UTC**. All **299** authenticated status samples remain verified, attached and
held over **99.992 seconds**. Verification ages are **18–2009 ms**, with fifty
advancing verification timestamps. Captured runtime logs contain no shadow or
registry authorization failure. The probe observes no fencing transition and
does not attempt a stale handshake. Unavailable-evidence acceptance is still
unexercised; a policy document/simulation is not proof of effective live denial.

Fresh read-only IAM checks confirm the policy is absent and only the ordinary
execution policy remains. The exact submitted document and procedure/config
are archived with the attempt. Current run, activation, deadline and real
streams remain. CloudTrail independently records **151 successful
`DescribeThing` calls** between 08:34:00 and 08:39:00 UTC from this exact VM's
assumed execution role; the registry is not being read under another principal.
The reason the shadow denial did not affect live requests within this window
is not established. IAM propagation/caching is a possible explanation, not a
finding; [AWS documents eventual visibility](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot.html#troubleshoot_general_eventual-consistency)
but does not establish this attempt's cause or a guaranteed cutoff.

The former shadow procedure is marked superseded rather than retried unchanged.
Prepared a separate `run-registry.md` and `deny-tbot-registry-read.json`. They
temporarily deny only `iot:DescribeThing` on this TBot for the same dedicated
execution role, using a new unique policy name. They leave all shadow reads,
registry contents and other principals/Things unchanged. The released poller
requires `projection -> has_capability(DescribeThing) -> agent assignment` to
complete; a failed registry read therefore prevents fresh authorization and
must expire the last verification. This is unavailable registry eligibility
evidence, not proof of unavailable shadow reads or capability removal.

Read-only IAM simulation validates only the exact TBot registry read is denied;
shadow reads remain permitted and writes denied. Six checks execute the new
procedure's extracted exact-document restoration logic without AWS calls.
POSIX parsing and ShellCheck pass. The existing authenticated status/cutoff/
stale-handshake probe is unchanged. This remains a bounded operator-run fault
with a fresh Disarmed held-control baseline, exact frozen run/time guard,
guarded recovery and no reacquisition. Acceptance requires the real API error,
measured verification expiry, board release and stale-ingress evidence; the
implementing agent has performed no cloud mutation or physical action.

Evidence: `tmp/issue-170/unavailable-evidence/attempt.8nRp9F/verified-no-observed-fault-summary.json`,
`post-check/verified-registry-call-identities.json`, raw samples/restoration,
`registry-policy-simulation-verified.json`, `registry-restore-checks.json` and
the new reviewed procedure. The first bounded capture completed with 180
samples/no read errors; a new bounded read-only capture covers the registry
attempt. No acceptance checkbox changes.

### Spontaneous MAVLink/control loss before the registry fault — 2026-11-03

Before running the new fault, the operator reports `control=1 -> control=0`,
telemetry `2 -> 1 -> 2` and QGC parameters failing to load. No registry-attempt
directory exists and fresh IAM inventory contains only the ordinary execution
policy. The registry fault was not applied. The baseline is invalid and the
operator is told not to inject the fault or reacquire control.

Independently valid runtime JSON events show held control through **08:54:49.906
UTC** and lost control with `control request timed out` by **08:54:54.921**.
The request deadline is three seconds; these samples do not identify the exact
pending request or timeout instant. MAVLink receipt stops at **160,001
messages**; the fifteen-second silence recovery is sampled by **08:55:04.950**,
and receipt is advancing again by **08:55:14.979**. The replacement telemetry
peer is `17936961041077991`; the old peer is `17936935043155083`. Video peer
`17936935043155229` remains connected with increasing actual frames across the
interval. The VM/run/activation/deadline remain unchanged. Parsing includes
standalone valid status JSON events because SDK output sometimes splits the
`microvm status` prefix from its JSON; no malformed/interleaved sample is
reconstructed into invented evidence.

Board **1442** holds QGC/mavlink-2/epoch 4 while Disarmed. Version **1443** is
unowned, and subsequent samples remain Disarmed with a fresh FC heartbeat and
no owner. All **52** captured lifecycle/board samples stay actual REDCON 1 and
Disarmed, with only the same assigned nonterminal VM. Recovery does not
automatically reacquire control. This resembles the earlier intermittent
timeout symptom; it does not prove an identical root cause or a repair.

The operator preserves board logs before the next inactive transition.
`board-capture.N462HC` records kernel 6.18.58-0-rpi, boot
`8c39b6d0-05fe-460f-ab00-f742916098de`, daemon 0.18.12 and KVS master 0.18.6
with the previously verified executable hashes. All four services are started,
and wlan0 has its ordinary pfifo_fast qdisc with no fault filters. The saved KVS
log contains the failure window. The kernel log/final completion marker are
not present in the inspected capture, so no kernel-fault exclusion is claimed.

Board diagnostic instance 3 matches the original agent association's callback
counts. Between **08:54:52.252 and 08:55:02.253 UTC**, callbacks stop advancing,
but **632 telemetry sends and 632 SDK calls complete**, with zero additional
SDK failures, SDK status zero and no pending operation in the sampled records.
The cloud's old association meanwhile has frozen ICE/data-channel counters and
increasing last-receipt age. These observations do not show a persistent
blocked bridge/SDK call on the board; API success does not prove packet egress
or remote delivery. No specific SDK lock, network cause or production fix is
claimed. The live transport finding stays open.

The original activation then expires without rollover. AWS records VM
`microvm-540672e3-150f-3d19-8fe3-96abfdbe6464` **TERMINATED at 10:01:37.176
CET**, reason maximum lifetime, **3.176 seconds after** the absolute 10:01:34
deadline. The complete nine-VM inventory has zero nonterminal entries.
Controller repair clears the expired run and endpoint; later captures through
**09:04:33 UTC** remain actual REDCON 1, expired with the same activation and
zero VMs. This records service termination separately from the unmeasured
authority cutoff. The bounded expiry recorder completes after 29 samples.

The operator subsequently confirms REDCON 4. Fresh reads verify actual born 4,
a matching directly observed inactive controller record, no run/endpoint and
all nine VMs terminal. `run-registry.md` is visibly held because its frozen run
has expired. A later normal activation and fresh reviewed baseline are needed;
there is no same-activation extension or test retry on the expired endpoint.
The operator has been asked for that activation while staying Disarmed and QGC
disconnected. Transport diagnosis and unavailable-evidence acceptance remain
open; no checkbox changes or production changes are made.

Evidence: `tmp/issue-170/pre-registry-transport-loss/verified-spontaneous-loss-summary.json`,
`board-capture.N462HC/mavlink-diagnostics-window.json`, raw KVS/SDK/runtime and
board/lifecycle samples, `expiry/verified-expiry-summary.json` and
`inactive/verified-inactive.json`.

### Fresh observer activation for the registry-evidence test — 2026-11-03

After the verified inactive observation, the operator reports actual REDCON 1
with QGC disconnected. Fresh inspection confirms projection **1970**, a fresh
Disarmed FC heartbeat with two observers/no owner, and exactly one nonterminal
VM among ten listed VMs. The new activation is
`A6783781-B5FA-49D3-98E6-BDADBE87D3F4`, 1793697086–1793700086 (3000
seconds), ending **11:01:26 CET**. Run
`75E12349-843B-4DF2-8D89-1A14FEFBB1E4` uses VM
`microvm-eb3d72dd-3b6f-3029-bdce-744e9e285acf`, started **10:11:34.776
CET**, with remaining hosting maximum **2992 seconds**. This is a new
activation after inactivity, not an extension of the expired one.

The stack remains 0.1.1/image 4.0/budget 3000 with both controlled launch gates
true and the unchanged released controller checksum. Only the ordinary
execution policy is listed. Thirty-six healthy runtime samples match the
released build and new assignment, with increasing real telemetry/video and
no attachment or held control. This finite observation does not repair or
waive the preceding transport timeout.

Refreshed the frozen configuration and `run-registry.md` only after those
checks; archived its previous frozen configuration/procedure. POSIX parsing
and ShellCheck pass for both the main block and recovery. Policy scope,
probe and restoration logic are unchanged. A new bounded read-only recorder
covers the attempt. The operator is asked for a fresh Disarmed control grant
and twenty-second baseline, and explicitly to leave the fault unrun if control
drops first. The same exact-run/time/fresh-lease guards remain; only the
operator creates tokens or changes IAM. Actual unavailable-evidence and stale
ingress acceptance remain pending.

Evidence: `tmp/issue-170/unavailable-evidence/registry-reactivation/verified-fresh-run-summary.json`,
raw VM/stack/policy/shadows/runtime, and the refreshed frozen operator package.

### Intermittent real registry denial, below the verification deadline — 2026-11-03

The operator runs `registry-attempt.555uer` with a valid held-control baseline.
The exact reviewed registry denial is submitted at **09:21:03 UTC** and
removed/confirmed absent at **09:22:45 UTC**. The probe records **299**
authenticated status samples, all verified/attached/held. Unlike the earlier
attempts, the exact tested VM's log stream contains real `iot:DescribeThing:
AccessDeniedException HTTP 403` at **09:22:23.464**, **09:22:48.556** and
**09:23:03.608 UTC**. The latter two occur after the saved probe window and
recorded policy removal; fresh read-only inspection independently confirms
absence.

Sampled verification ages range **20–7948 ms**, with **46** advancing complete
verification timestamps. Successful verifications therefore continue between
denials; the observed gap never reaches the fifteen-second cutoff. The probe
correctly reports no fencing transition and attempts no stale handshake.
This is partial real unavailability, not acceptance of continuous verification
loss, nor evidence that the runtime ignored an expired verification. IAM
propagation/caching is a plausible explanation for the mixed results and late
denials; it is not independently established as this attempt's cause. The
[IAM eventual-visibility guidance](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot.html#troubleshoot_general_eventual-consistency)
does not guarantee an effective-denial time.

Fresh read-only inspection confirms `NoSuchEntity` for the temporary registry
policy and only the ordinary execution policy listed. Later observations of
the same run remain actual REDCON 1 with healthy telemetry/video, fresh
Disarmed/Hold FC state, no owner and runtime control `operator released`.
The operator's later release is distinct from a verification shutdown. No
replacement or cutoff latency is claimed.

Archived the executed procedure/configuration/probe and submitted policy.
Revised only the temporary probe/operator wait to a bounded **180 seconds**,
without changing the native four-minute cutoff or released code. A new probe
guard immediately refuses attachment/control loss while verification remains
valid, so an independent timeout/client expiry cannot be accepted as the
verification-loss case. Later expiry during the recovery wait is recorded
separately. Five local probe checks pass, including both independent control
loss and attachment loss without a stale-handshake attempt; POSIX parsing and
ShellCheck pass. Exact policy scope, frozen run/time guards and bounded
restoration remain. The operator reviews before starting a fresh grant and
runs promptly after the twenty-second Disarmed baseline. Actual continuous
unavailability/cutoff/stale-ingress acceptance remains pending.

Evidence: `tmp/issue-170/unavailable-evidence/registry-attempt.555uer/verified-intermittent-denial-summary.json`,
the tested log stream's saved errors, raw status/restoration and archived
executed probe/procedure. No acceptance checkbox, production artifact,
deployed configuration, AWS resource or device state is changed by the
implementing agent.

### Native cutoff interrupts the longer registry trial; physical access unavailable — 2026-11-03

`registry-attempt.y1WLCJ` starts from a valid held-control baseline. The
registry denial is submitted at **09:33:42 UTC**. After **178.035 seconds**
and **527** authenticated status samples, the new independent-loss guard
stops the probe: the last sample at **09:36:40.052 UTC** is detached/unheld
while still verified, with verification age **3484 ms** and `operator
released`. The operator supplies the native terminal sequence: control grant,
`control=0 attachment closed`, then `attachment token lifetime ended; start a
new explicit attachment`. This confirms the native client cutoff; it does not
prove AWS server-token expiry or a WebRTC failure.

All 527 samples remain verified; the first 526 remain held. Verification ages
range **4–9685 ms**, below the fifteen-second deadline. The policy is
removed/confirmed absent at **09:36:42 UTC**, and fresh IAM reads independently
confirm only the ordinary execution policy remains. No stale handshake is
attempted. This trial remains inconclusive for continuous verification loss
and held-control release at that cutoff. Its executed policy, procedure,
configuration and probe are archived; the procedure is visibly held against
unchanged retries. The released fifteen-second bound and native cutoff are
unchanged.

CloudTrail independently records **211 successful and 90 denied
`DescribeThing` calls** for the exact VM role during **09:33–09:43 UTC**.
Denial messages identify the exact TBot ARN and an identity-policy explicit
deny, including delayed denials after recorded policy removal. This confirms
mixed effective authorization; it does not establish a guaranteed IAM cache
lifetime. A later clean observer preflight contains **42** fresh verified,
unattached/unheld samples spanning **205.613 seconds**, with advancing actual
telemetry/video and zero registry 403 events in that window. Fresh board
**1463** is Disarmed with a ready heartbeat/no owner. Read access has recovered
before preparing a different live case.

Prepared the separate whole-device-death procedure and a bounded read-only
capture. The operator then reports no current physical access to TBot. No
whole-device power-off is performed; **device death remains pending**. The
death procedure is marked held. A later Office REDCON 4 transition must not be
counted as DDEATH. Unavailable-verification acceptance and independent REDCON
2/1/video behavior also remain open, along with the unresolved transport
finding and final operator cost/publication acknowledgement.

Prepared `tmp/issue-170/disabled-return/disable.md` and its reviewed parameter
file for an operator-run return to disabled gates. It changes only
AutomationEnabled/PrerequisitesConfirmed to false, preserving budget 3000,
release 0.1.1/image 4.0, controller code, previous template, activation history
and shutdown-repair schedules. Exact stack, born REDCON 4, matching observed
inactivity, no run/endpoint, complete terminal inventory, ordinary role policy
and released-code guards precede submission. POSIX parsing, ShellCheck and
**28** actual-block sh/zsh mocked guard/update/wait cases pass; no real AWS
mutation occurs in those checks. The operator has been asked to set actual
REDCON 4 before this update. **The gate update has not been run.** The latest
read at **09:54:48 UTC** still shows actual REDCON 1 and the one active VM.

A fresh read-only Frankfurt inventory at **09:56:39–09:56:43 UTC** records five
agent/probe images and eight versions (six successful/two failed), ten listed
VMs (nine terminal/one running), only the default plus cloud-MCU VPCs, no NAT
gateways/Elastic IPs/network interfaces/ECR repositories, and only the separate
cloud-MCU ECS cluster. The agent S3 prefix retains **20 versions / 43,554,530
bytes**. Production MicroVM logs retain fourteen days, probe seven; reported
storedBytes are 630,124 and zero. Retained image/snapshot, storage/log and
usage-based costs remain; this is not a billing statement or final zero-compute
inventory. No cleanup or cloud-MCU change is performed.

Evidence: `tmp/issue-170/unavailable-evidence/registry-attempt.y1WLCJ/verified-client-cutoff-summary.json`,
its CloudTrail/runtime/role audit, `device-death/verified-active-preflight.json`,
`disabled-return/disable-mock-checks.json`, `disabled-return/checkpoint-summary.json`
and `cost-inventory-20261103/verified-summary.json`. #170 remains open, with no
new complete acceptance checkbox and no implementing-agent cloud/device
mutation, production change or commit.

### Inactive return verified; disabled update awaiting operator — 2026-11-03

The operator reports actual REDCON 4. Fresh inspection at **10:03:07 UTC**
confirms projection **1973**, a matching directly observed inactive controller
record (`inactiveObservedAt=1793700154`), no run/endpoint and all **ten** listed
VMs terminal. The last activation ID/start/deadline are preserved, and only
the ordinary execution-role policy remains. The live stack's normalized
parameters/status/revision still exactly match the reviewed disable package.

The last VM's actual termination is **11:01:29.142 CET**, reason maximum
lifetime, **3.142 seconds after** the activation's 11:01:26 deadline. This
precedes the later directly observed inactive state; it is recorded as lifetime
termination, not a new REDCON 4 shutdown or the unperformed DDEATH case. No
authority-cutoff latency is inferred from that service timestamp.

The operator has been asked to review/run the complete guarded
`disabled-return/disable.md` block. It preserves every parameter except the two
launch switches, which become false, and uses the previous template. The
implementing agent has not submitted that AWS mutation. After operator success,
verify the disabled controller/configuration, enabled repair/watch schedules,
unchanged release/code/history and complete regional agent/probe inventories
again. Physical death, unavailable-verification and independent REDCON 2/1/
video cases remain pending, as do the open transport finding and operator
cost/publication acknowledgement; #170 remains open.

Evidence: `tmp/issue-170/disabled-return/verified-inactive-summary.json` and
its raw projection/agent/VM/inventory/stack/role responses. POSIX parsing,
ShellCheck and the previously recorded 28 mocked block cases pass. No new
production artifact or commit is created.

### Disabled operation and cost acknowledgement verified — 2026-11-03

The operator's guarded update finishes at **10:05:42 UTC**. Fresh AWS reads
confirm `UPDATE_COMPLETE` with **AutomationEnabled=false** and
**PrerequisitesConfirmed=false**. Only those two parameters change. Release
**0.1.1/image 4.0**, controller ZIP/checksum, budget **3000**, other controller
environment fields and activation history are preserved. The controller is
Active/Successfully updated with automation disabled and reserved concurrency
one; the lifecycle IoT rule is disabled. Controller repair and the independent
witness watch remain enabled at one-minute schedules, targeting their expected
functions. Witness still watches the same dedicated image.

Actual REDCON 4/projection **1973** and the matching observed inactive state
remain, without a run/endpoint. Complete paginated inventories across **all
five** retained agent/probe images contain **ten terminal VMs and zero
nonterminal VMs**. A repeated inventory **151.184 seconds** later, at
**10:09:33 UTC**, remains zero with no restart. This accepts the disabled
return/zero-compute checkpoint, without claiming the pending physical
device-death case has occurred. Read-only networking/resource evidence remains
under `cost-inventory-20261103/`; no retained-resource cleanup or cloud-MCU
change is performed.

The operator explicitly answers **Acknowledged** to retained S3/log/image/
snapshot, API/event and data/TURN costs; zero VMs does not mean zero total AWS
charges. The acknowledgement also covers immutable versioned artifacts,
operator-run publication, selection for later launches, preserved existing
release/deadline and disarm/release/drain before immediate replacement. The
corresponding whole operator-cost/publication acceptance checkbox is now
checked. No other checkbox is newly accepted at this checkpoint.

Corrected the misleading named-shadow ARN statement in
[the watch constraint](constraints/agent-watch.md#scope-and-failure-handling).
Named resources include `/sparkplug` or `/agent`; the deployed witness's
`thing/*` wildcard covers those resources. Controller-only agent writes remain
an application ownership rule under that deployed wildcard. This is a
documentation correction supported by the AWS action-resource reference,
the prior #165 permission finding and the #170 IAM simulations. No deployed
permission or runtime behavior changes, so no new runtime release is needed.

**#170 remains open.** Required live evidence is still missing for continuous
unavailable-verification fencing/held-control release and stale ingress,
independent real REDCON 2/1/video behavior, and whole-device DDEATH termination.
The intermittent control/telemetry timeout and camera recovery limitations
remain explicit. Actual remaining physical cases require operator availability;
the whole-device case cannot proceed without physical access. Leave the device
at REDCON 4, QGC disconnected and both launch gates false until a separately
reviewed controlled test resumes. No automatic commit or further milestone
work is performed.

Evidence: `tmp/issue-170/disabled-return/post-disable/verified-disabled-summary.json`,
initial/repeated complete inventories, stack/controller/rule/target/shadow
responses, `operator-acknowledgement.json`, and the before/after tracker bodies.
The gate rollout was operator-run; local operator-block validation remains
28 mocked sh/zsh cases plus POSIX/ShellCheck and `git diff --check`.

### Remote continuation prepared after physical-access constraint — 2026-11-03

The operator asks to continue the remaining checks without physical access.
Verification-loss/held-lease fencing and stale ingress can be exercised through
existing Office/QGC/AWS access on the previously confirmed secured Disarmed
setup, without an arm or drive action. Video/transport diagnosis can continue
over the existing board SSH path; actual REDCON 2/1 recovery must still be
demonstrated and its known camera limitation is not waived. Whole-device
DDEATH continues to require physical power control of both MCU and Pi.

Prepared `tmp/issue-170/scheduled-verification-loss/overview.md`, guarded
remote `enable.md`, dated-policy `stage.md`, `probe.md` and exact-document
recovery. After a verified new observer run, staging schedules only the agent
role's exact TBot `DescribeThing` denial **fifteen minutes ahead for two
minutes**. A fresh native attachment starts shortly before that window. This
separates IAM propagation allowance from the native client cutoff; it changes
neither the runtime's fifteen-second verification bound nor the four-minute
native cutoff. The date window bounds the denial statement; explicit policy
removal and recovered-read evidence remain required. IAM propagation and live
date-condition effects are not accepted from simulation alone.

[AWS date-condition documentation](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_examples_aws-dates.html)
supports this test design. **60 read-only IAM simulation decisions** validate
before/start/during/end/after scope and timing, **28** actual-block sh/zsh
mocked enablement cases pass, and **21** stage/probe cases cover wrong role/run,
owned/unsafe baseline, short budget, broadened policy, nonrunning VM, early/
late start, rejected/ambiguous put, interruption, altered policy, probe loss
and failed cleanup. All those operator-block tests use mocked AWS/network
boundaries. POSIX parsing and ShellCheck pass. The status/WebSocket probe is
byte-identical to the existing tested probe; no actuator or acquire frame is
sent by it. Fresh-run stage/probe configuration remains explicitly held until
the new deployed assignment has been reviewed.

Fresh read-only preflight still shows the reviewed disabled stack, actual
REDCON 4, no run/endpoint and all dedicated-image VMs terminal. No new live
experiment has started. Requested the operator's reviewed two-switch
enablement, remaining at REDCON 4/QGC disconnected until another directly
observed inactive checkpoint. Normal activation, staging and timed attachment
are separate subsequent reviewed actions, followed by return to disabled
operation and a complete terminal inventory.

Separate Scheduler migration edits appeared concurrently in the workspace.
This experiment uses the existing deployed template and exact stack-revision
guard, preserving those edits. If that rollout happens first, refresh the live
stack/schedule preflight before enabling. No Scheduler migration, runtime
publication, AWS mutation or commit is performed by this experiment's
preparation. #170 remains open with the same three whole criteria accepted.

### Remote timed experiment enabled, fresh observer verified and policy staged — 2026-11-03

The operator completes the guarded remote enablement at **10:34:50 UTC**.
Fresh reads confirm both gates true, release 0.1.1/image 4.0/budget 3000 and
unchanged controller checksum. The controller directly observes inactive
REDCON 4 after that update (`inactiveObservedAt=1793702109`), with no
assignment or nonterminal VM. Both shutdown schedules remain enabled; fresh
resource lookups show the existing scheduled EventBridge rules, not the
separate uncommitted Scheduler migration.

Normal Office activation reaches actual REDCON 1/projection **1979**. New
activation `57CBC1C8-3F3B-443F-BB8B-2733F46A6A35` spans
1793702242–1793705242, exactly 3000 seconds, ending **12:27:22 CET**. Run
`30D933A0-B88E-4E19-9C2E-69E67A2C7DCC` uses image 4.0 VM
`microvm-465c406d-d137-38aa-9fb2-e0ab36dd54c5`, started **11:37:26.778
CET**, remaining hosting maximum **2996 seconds**. Fresh board **1470** is
Disarmed/heartbeat fresh with no owner. The first runtime capture has video
still connecting; later **15** healthy samples show both real streams
increasing on the same run with no attachment/held control and the exact
released build. The frozen staging identity is prepared only after that
later evidence. Native `agent::build` passes without creating an attachment;
its hash/log are retained to reduce build delay before timed attachment.

The operator runs `stage.ctQHeW`. Independent IAM reads verify its exact
two-date TBot-only registry denial, matching role/policy and the same current
run/activation with fresh Disarmed/no-owner state. The saved window is:

| Event | UTC | Europe/Berlin |
| --- | --- | --- |
| Fresh native attach command | 10:56:09 | **11:56:09 CET** |
| Denial statement begins | 10:57:39 | **11:57:39 CET** |
| Denial statement ends | 10:59:39 | **11:59:39 CET** |

The operator is asked to review `probe.md` before the attachment time, connect
QGC, wait twenty seconds after a fresh Disarmed `control=1`, then promptly run
the whole probe block. No reacquisition is allowed during recovery. A missed
window or early control loss requires the exact recovery block and an
inconclusive result, not a fabricated cutoff. Only the operator performs token
creation/policy removal. A bounded thirty-minute read-only recorder covers
warmup, fault and recovery. The date condition has not yet been observed
denying reads, so no fencing/stale-ingress acceptance is claimed at staging.

Evidence: `tmp/issue-170/scheduled-verification-loss/enabled-check/verified-enabled-inactive-summary.json`,
`activation-check/verified-observer-summary.json`, `stage.ctQHeW/verified-staging-summary.json`,
raw configuration/stream/role/window evidence, native prebuild hash/log and
the reviewed probe/recovery. Concurrent workspace changes are preserved;
no new runtime publication, agent-executed AWS mutation or commit occurs.

### Timed registry denial fences held control and stale ingress — 2026-11-03

The operator completes `stage.ctQHeW/probe.09XTtI`. Its **134** authenticated
HTTPS samples begin at **10:57:09.642 UTC**, with the exact released build,
reviewed VM/run/activation/deadline, attached and held. All **133** samples
before fencing retain attachment/control and verified assignment; this is not
the earlier native four-minute cutoff. CloudTrail attributes **eight**
consecutive `DescribeThing` explicit identity-policy denials to the tested
execution-role session and exact TBot ARN, **10:57:40–10:57:54 UTC**, after
the last successful old-run registry read at **10:57:38 UTC**. Runtime logs
independently contain HTTP 403s at 10:57:42.204, 10:57:47.222 and
10:57:52.240 UTC. Successful reads do not reset the timer during this fault.

At **10:57:53.893 UTC** the probe observes phase `stopped`,
`assignmentVerified=false`, `attached=false`, `controlHeld=false` and
`stopReason="lifecycle unverified for 15 seconds"`. The last true sample has
assignment age **14,961 ms**; the first false sample has inferred age
**15,285 ms**, calculated from runtime uptime minus the last verified uptime.
This brackets the transition across the fifteen-second threshold with
**324 ms** sampling separation; it does not measure an exact cutoff latency.
The following authenticated stale `/stream` handshake receives a valid
WebSocket upgrade and then the connection closes. No acquire, MAVLink or
actuator frame is sent. The result proves closure of unusable application
ingress, not HTTP-level rejection before upgrade or a test of stale command
delivery.

Board shadow **1473** holds the QGC/mavlink-3 epoch-1 five-second lease before
loss. The first released capture at **10:57:54.607 UTC** contains shadow
**1476**, heartbeat fresh, Disarmed/Hold and no owner; its arm-state metadata
was updated at 10:57:53 UTC. The board remains disarmed and unowned through
**11:11:40.364 UTC**, **825.757 observed seconds** after that first released
sample. No regrant is observed. Five-second board sampling does not establish
exact click-to-release or fence-to-release latency. Across all **360**
capture samples, actual REDCON remains **1**, projection **1979**, activation
and deadline remain unchanged, and complete production inventories contain
at most one nonterminal VM. No physical lifecycle transition is substituted
for missing verification.

The operator removes the temporary policy at **10:57:56 UTC**. Fresh IAM
inspection lists only `ObserveAndVerifyAssignments`; later successful
`DescribeThing` calls from the replacement role session and fresh runtime
assignment verification establish restored reads. The old VM is actually
**TERMINATED** at **11:58:10.690 CET**, reason `Success.`, well before the
activation deadline. Its shadow endpoint is cleared; repair creates run
`6FDB7ADB-4ECD-47C0-ABBA-A0C2BB7A1E95`, VM
`microvm-c4dd3d21-b509-351e-a6ba-71ada6cfcca6`, at **12:00:21.019 CET**,
with hosting maximum **1622 seconds**, the same activation
`57CBC1C8-3F3B-443F-BB8B-2733F46A6A35` and deadline **12:27:22 CET**.
All **323** parsed replacement runtime samples are unattached and unheld;
**318** later healthy samples have actual telemetry and video receipt,
increasing to **100,618 MAVLink messages** and **44,823 encoded frames**.
Initial connecting/zero-counter samples remain in the record. AWS later
records replacement termination at **12:27:25.017 CET**, consistent with the
unchanged hosting ceiling; this is not a claim of authority after deadline.

A separate operator rollout changed the deployed controller repair from its
scheduled rule to Scheduler during this experiment. CloudFormation update
begins **10:59:11.961 UTC**, after the verification cutoff and old-VM
termination, and finishes **11:00:15.807 UTC**, before replacement startup.
The replacement therefore demonstrates recovery under the now-deployed
Scheduler template, rather than an unchanged scheduling deployment. Controller
code hash, selected release/image and budget remain unchanged. Fresh reads
show both controller repair and independent witness watch as enabled
one-minute Scheduler schedules; enabled state alone does not establish each
schedule's successful delivery. The final disable block reuses that deployed
template.

On receiving the delayed result at **13:28 UTC**, fresh reads find a later
activation `E64C930A-A367-4744-A6E4-2336AD1E28E5`, already inactive at actual
REDCON 4/projection **1990**, with no run or endpoint. That later activation
is separate from this fault; continuous REDCON/activation proof above ends
with the saved capture. All five retained image inventories at
**13:31:51 UTC** contain zero nonterminal VMs (eleven listed terminal
production records). The operator confirms REDCON 4 and runs the refreshed
two-switch disable block preserving the later activation history. Its final
post-update inspection is recorded separately.

Evidence: `tmp/issue-170/scheduled-verification-loss/post-probe/verified-probe-summary.json`,
saved status samples and probe result, thin attributed CloudTrail events,
runtime logs/statuses, the completed thirty-minute capture, terminal VM
responses, current deployment/Scheduler documents and complete inventories.
`audit_completed_probe.py` checks these saved sources without reading tokens
or contacting services. Earlier failed IAM attempts remain inconclusive; this
successful dated fault does not relabel them. The held-verification-loss and
stale-ingress subcases now pass. Independent REDCON 2/1/video recovery,
whole-device DDEATH and the unresolved transport/camera findings remain open;
no full released-system acceptance or issue completion is claimed.

### Post-experiment disabled return and zero compute verified — 2026-11-03

The operator completes the refreshed two-gate disable block at **13:33:22
UTC**. Fresh inspection from **13:34 UTC** verifies `UPDATE_COMPLETE`, both
launch parameters false, controller automation `disabled`, the lifecycle IoT
rule disabled, unchanged controller code/release 0.1.1/image 4.0/budget 3000
and preserved later activation `E64C930A-A367-4744-A6E4-2336AD1E28E5`.
Actual REDCON 4/projection **1990** matches the observed inactive controller
record, with no run or endpoint. Both one-minute Scheduler schedules remain
enabled, and only the ordinary execution-role inline policy remains.

Complete inventories across **all five** retained agent/probe images contain
zero nonterminal VMs. Initial inspection lists eleven terminal production
records; the repeated inspection at **13:38:03–13:38:08 UTC**, **231 seconds**
after initial read start, lists ten. Historical records can leave the listing;
neither count represents total lifetime launches. Both inventories are
complete and zero, with no restart. Explicit saved `GetMicrovm` responses
retain terminal evidence for the tested and replacement VMs independently
of list retention.

Fresh networking reads show only the default VPC plus the separately owned
cloud-MCU VPC, no NAT gateways, Elastic IPs, network interfaces or ECR
repositories, and only the existing cloud-MCU ECS cluster. No cleanup or
cloud-MCU change is performed. Retained artifact/image/snapshot/log and
usage costs remain covered by the earlier operator acknowledgement; zero
VMs does not imply zero total AWS charges.

The combined contention/authority-loss whole criterion is now checked:
busy rejection, explicit takeover/lease loss, QGC inactivity, attachment
closure, real UDP-path loss/recovery, lifecycle shutdown and the newly proven
unavailable-verification case each retain their own released-system evidence.
This brings the accepted whole criteria to **four**. The duplicate/stale and
independent-recovery whole criterion remains unchecked because independent
video recovery still needs proof. Physical whole-device DDEATH, actual
REDCON 2/1/video independence and unresolved transport/camera findings keep
**#170 open**. Leave actual REDCON 4, QGC disconnected and both gates false
until the next reviewed case. No new runtime release, automatic commit,
agent-executed AWS mutation or firmware action occurs.

Evidence: `tmp/issue-170/scheduled-verification-loss/disabled-return/post-disable/verified-initial-disabled-summary.json`,
`verified-repeated-disabled-summary.json`, raw stack/controller/shadow/rule/
Scheduler/policy/network and complete inventory responses. The local saved-data
audits, POSIX/ShellCheck validation of the refreshed operator block and
`git diff --check` pass. These checks audit actual operator-run publication
state; they do not replace the remaining live cases.

### Further remote checks: camera limitation and Scheduler witness fixture prepared — 2026-11-03

The operator requests further progress without physical access. Source review
and the retained #167 camera cases identify a limit on the old unbind method:
the board worker closes failed video and publishes ERROR before camera cleanup,
then preserves MAVLink while waiting for a supervised worker restart. Its fatal
camera path does not restart video in the same worker. Earlier Unicam rebind
did not restore the camera. Repeating that method can exercise released-cloud
1→2 isolation and actual-2 entry, but cannot establish independent 2→1 recovery
or repair the known camera cleanup wait. No retry behavior or device capability
is changed to manufacture acceptance.

Selected a separate remote check that can keep the real TBot at actual
REDCON 4: revalidate independent witness orphan repair on released image 4.0
after the Scheduler migration. #168's successful image-1.0/scheduled-rule test
is historical. The existing watch constraint already defines controller
isolation, the 120-second grace, an unassigned 600-second fixture, terminal
evidence and restoration. This phase leaves both ordinary launch gates false,
creates no operational assignment, and opens no attachment or actuator path.

Fresh read-only preflight finds the reviewed disabled 0.1.1/image-4.0/budget-3000
stack, actual REDCON 4/projection 1990, matching inactive controller state with
no run/endpoint, unchanged activation history and terminal listed production
VMs. Controller concurrency is one. Both new Scheduler schedules are enabled
with their exact target/role/payload and one-minute rate. Witness still selects
the dedicated image and has code checksum
`PRokWCk5a6LAmF/cIiq7hmB866yBf+mGJL6TsFdnuwA=`; its timeout is thirty seconds.
Controller checksum remains the released value and its timeout is 120 seconds.

Prepared `tmp/issue-170/remote-watch/{overview,isolate,launch,recovery}.md`.
The first operator block launches no VM: it rechecks both stack revisions,
function identities/checksums, inactive projection/history, complete terminal
inventories, concurrency and both exact schedules; pauses only controller
repair, sets controller concurrency zero and waits 130 seconds. Witness stays
enabled. Failure after a possibly applied mutation attempts restoration only
against the unchanged reviewed configuration and reports any restoration
failure. A changed schedule is not overwritten. Recovery refuses nonterminal
inventories, foreign concurrency or changed code/targets.

After fresh isolation verification and a bounded read-only recorder are ready,
the separate held launch block generates one unique request immediately
before launch, with image 4.0, a 600-second hosting cap and matching deadline.
The real TBot shadow is unchanged. An atomic launch-once marker refuses a
second request under that isolation; ambiguous responses preserve the identical
request for inspection. Require nonterminal hosting within the orphan grace,
an exact-VM witness request after the grace and actual terminal state before
the platform cap. Manual termination, failed hooks and platform expiry cannot
pass witness acceptance. Restore controller concurrency one and the original
repair schedule only after terminal confirmation, then repeat zero-compute
checks. No fixture has been launched by the implementing agent.

Scheduler update requests derive from the reviewed `GetSchedule` documents,
preserving all optional mutable fields while excluding only service metadata.
This follows AWS's [UpdateSchedule replacement semantics](https://docs.aws.amazon.com/scheduler/latest/APIReference/API_UpdateSchedule.html).
Local validation runs the actual conditional operator blocks with CLI doubles:
**46 scenarios** across ten test methods, including sh/zsh isolation, guard
refusals, ambiguous writes, signals, failed restoration, unchanged-field
preservation, foreign concurrency and duplicate launch refusal. POSIX parsing,
ShellCheck, collector syntax and `git diff --check` pass. No real mutation is
executed by those tests, and mocks/preparation accept no new live criterion.

The operator has been asked to review recovery and run only the isolation
block, retaining REDCON 4/QGC disconnected. Isolation, launch, witness request,
terminal compute and restored settings still require actual operator evidence.
The physical DDEATH case and independent video/REDCON 2/1 requirement remain
open. No runtime change, new release, automatic commit or other milestone work
is introduced.

### Released-image orphan repair through witness Scheduler passes — 2026-11-03

The operator completes `remote-watch/isolation.RpmKGO`: controller repair is
paused and reserved concurrency set to zero at **14:25:46 UTC**, followed by
the recorded drain through **14:27:58 UTC**, **132 seconds** beyond the
controller's reviewed 120-second timeout. Fresh reads at **14:29:21 UTC**
confirm isolated controller, unchanged enabled witness schedule, disabled
ordinary launch gates, unchanged code/release/image/budget, actual REDCON 4,
no assignment/endpoint and all five image inventories terminal. The completed
read-only capture begins at **14:29:55 UTC**.

The separately directed operator launch `launch.ryQWiY` creates one deliberately
unassigned image-4.0 VM:
`microvm-c31d264f-03bd-3aed-80bb-9af89a3ee8bb`, started **15:32:11.588 CET**,
with a **600-second** hosting cap and a matching fresh absolute hook deadline.
Its unique `watch-orphan-170-…` identity is never installed on the real Thing.
An initial PENDING response is preserved. The VM is RUNNING in multiple later
reads, including age **119.307 seconds**, inside the 120-second orphan grace.

Witness logs an exact-VM termination request at **14:34:15.462 UTC**,
age **123.874 seconds**. AWS records actual **TERMINATED** at
**15:34:15.833 CET**, age **124.245 seconds**, reason `Success.` This is well
before the 600-second hosting cap, and is not a failed hook, manual drain or
platform expiry. The witness log is emitted after its termination API call,
so its timestamp does not measure request-start latency. The accepted bounded
result contains **26** saved VM samples and **four** isolation samples showing
concurrency zero, controller schedule disabled and witness schedule enabled.
The collected drained-window controller log response contains zero events.

The only parsed runtime status has the exact released build, unverified
assignment, no attachment/control and zero telemetry/video counters. Across
the bounded fixture evidence, real TBot agent shadow version **2378** and
its complete state remain unchanged, including activation history. Actual
REDCON remains **4**, projection **1990**. No device session, capability change,
operational shadow fixture or physical action manufactures the watch decision.
The unassigned-orphan branch is reached through the sweep handler; the
projection-only handler checks known assignments. With the dedicated schedule
enabled and no manual witness invocation in this procedure, the exact-VM log
supports scheduled sweep attribution. CloudTrail's optional corroborating
lookup has not returned a matching termination event at inspection; no
unobserved principal attribution is substituted for that absence.

After terminal confirmation the operator runs `recovery.i27OIi`. Fresh
inspection at **14:41:50 UTC** verifies controller concurrency **one**, both
Scheduler configurations restored exactly to their reviewed enabled values,
ordinary gates false, unchanged code/release 0.1.1/image 4.0/budget 3000,
ordinary execution-role policy only, actual REDCON 4 and unchanged activation
history without assignment or endpoint. Complete inventories across all five
images have zero nonterminal VMs. A repeat at **14:46:11 UTC**, **257.130
seconds** after the first restoration check, remains zero with no restart.
Both checks list nine retained terminal production records, rather than a
total lifetime-launch count. The recorder stops after **196** samples with
**zero** read errors.

This accepts independent orphan compute repair on the released image and new
Scheduler deployment with the primary controller unavailable. The real-device
death case and independent REDCON 2/1/video requirement remain separate. No
whole acceptance checkbox is newly satisfied; #170 stays open with four
accepted whole criteria. No new release, agent-executed AWS mutation, commit,
firmware action or unrelated cleanup occurs.

Evidence: `tmp/issue-170/remote-watch/launch.ryQWiY/audit/verified-orphan-summary.json`,
exact request/response, terminal VM reads, witness/runtime/controller log
responses, completed capture and
`recovery.i27OIi/verified-check/verified-{restoration,repeated-restoration}-summary.json`.
`audit_orphan_result.py` validates these saved sources without service calls
or token reads. The forty-six mocked operator scenarios remain supporting
validation; the acceptance above relies on the actual operator-run VM.

### Next observation-only remote video phase prepared — 2026-11-03

The operator confirms that existing board SSH access remains available after
wake. Prepared `tmp/issue-170/remote-video/enable.md` against the restored
disabled stack and activation history. Its previous-template update changes
only the two ordinary launch gates to true, preserving the released code,
image, budget and deployed Scheduler template. It requires actual REDCON 4,
a matching inactive observation/history, ordinary policies and terminal
inventory. Twenty-eight actual-block sh/zsh guard/failure cases pass, now also
checking the exact parameter input and `UsePreviousTemplate` in the CLI double;
POSIX/ShellCheck pass.

No QGC attachment, arm or drive action is planned. After separately verified
enablement/inactive observation, normal REDCON 1 activation and read-only SSH
preflight will establish the current boot, binaries and bound camera receiver.
A separately reviewed software camera fault can then test released-cloud
1→2 isolation. A subsequent real inactive interval with camera still unavailable
can test fresh actual-2 entry. Known normal power-cycle restoration does not
satisfy independent 2→1 recovery; that part stays open. No camera mutation is
prepared against an assumed driver identity, and no video-only case is accepted
from preparation.

### Released cloud camera isolation and fresh actual-2 entry pass — 2026-11-03

The observation-only phase is enabled at **14:51:12 UTC**, retaining release
0.1.1/image 4.0/budget 3000 and the deployed Scheduler template. Fresh inactive
observation follows. Normal wake produces activation
`0C05C14F-9023-4E5D-9CA0-081B91FDCAE3`, run
`E0828A9B-9ADC-476A-AD88-6966FD49658E`, VM
`microvm-0104d4d7-a234-3e7b-a510-7e1b13d4906b`, started **15:55:20.766 CET**
with remaining hosting allowance 2996 seconds. Twenty-five healthy samples
show actual telemetry/video receipt without attachment/control. Fresh board
1506 is Disarmed, heartbeat fresh, with no owner; actual REDCON is 1/projection
1996. Read-only SSH preflight records boot
`20bd7f2c-8d82-4e5d-9fba-f6e433f5e206`, kernel 6.18.58-0-rpi,
daemon 0.18.12/KVS 0.18.6 and the verified IMX708/Unicam receiver.

The operator's exact-identity guarded camera detach succeeds at **15:09:59
UTC**, without service restart. Actual REDCON reaches **2**, projection **1997**,
with video unavailable and agent/MAVLink still available. The bounded audit
contains **100** actual-2 samples spanning **495.002 seconds**, with the same
VM/run/activation/deadline, one nonterminal production VM and disarmed/unowned
board state. Eighty post-fault runtime samples retain verified assignment and
connected/error-free telemetry while video is stopped with its independent
`WebRTC connection lost: KVS status 0xd` error. Encoded video stops at **25,598**
frames; telemetry increases from **15,445** to **22,302** messages. All **96**
sampled telemetry diagnostics retain peer **17937177245771801**, connected with
no stop/replacement. This accepts real released-cloud **1→2 isolation**.

The command's post-SSH ninety-second wait and completion timestamp were skipped:
SSH consumed the remaining child-shell input. This is a preparation error,
not operator timing. The independent recorder supplies the actual sustained
hold above, so the detach is not repeated. Fixed current argument-form SSH
blocks with `-n`. Twenty-nine guarded camera scenarios pass, now requiring
post-SSH completion; a separate regression reproduces the old missing-wait
behavior when `-n` is removed. No production runtime change is involved.

To establish a fresh actual-2 entry without resetting the camera, the operator
stops only MAVLink at **15:25:11 UTC**. Saved markers show `closing_video` then
`releasing_camera`, without `camera_released`; the KVS main thread samples a
futex wait. These observations do not identify the exact userspace cause.
Actual REDCON **3**/projection **1998** is directly observed. The old VM is
**TERMINATED** at **16:25:14.454 CET**, **1201.546 seconds before** its saved
deadline; run/endpoint clear and production inventory is terminal.

The separately guarded restoration starts only MAVLink at **15:28:49 UTC** on
the same boot, leaving the camera unbound. Actual REDCON **2**/projection
**1999** authorizes new activation `D13A0D6D-9517-4530-8A6F-F6908BB99E11`,
run `D3EF5423-150F-48F3-8DA0-5661EDFD131F`, image-4.0 VM
`microvm-2dc27df1-eece-3d72-88f4-119ca7c3979a`. It starts **16:29:00.735
CET** with hosting maximum **2979 seconds** under the new persisted 3000-second
span. Initial connecting/unverified samples are preserved. **86** healthy
samples over **426.265 seconds** receive **7390** telemetry messages, with
**zero video frames**, no observed video peer, no attachment/control and one
nonterminal VM. Ninety actual-2 capture samples retain the new assignment and
disarmed/heartbeat-fresh board. This accepts **fresh released actual-2 startup**.

Before restoration, a read-only capture preserves **19** thread sections,
kernel wait/syscall metadata, camera-failure markers and libcamera 0.7.1 mapped
identities. None of the queried debugger/symbolization tools is available;
none is installed or attached. The main-thread futex sample does not prove a
particular library lock failure. The operator then returns actual REDCON 4,
projection **2002**; the data-only VM is TERMINATED at **16:41:54.213 CET**,
with inactive controller, preserved activation history, no endpoint/run and
terminal production inventory. This is ordinary board sleep, not device death.

Normal Office wake restores the camera on new boot
`eda4ac90-1fba-430c-acd0-bcd95a2fb92d`. Four services, binary hashes and the
bound Unicam receiver are reverified. A new released run receives **5136**
telemetry messages and **6568** video frames across **56** healthy samples,
unattached/unheld and Disarmed at actual REDCON 1/projection **2008**. This
normal reboot is recorded as restoration, not independent same-session 2→1.

Evidence under `tmp/issue-170/remote-video/`: activation-check,
camera-loss.Tf5Rvk/audit/verified-camera-isolation-summary.json,
mavlink-stop.kJNb2D/verified-check/verified-inactive-terminal-summary.json,
fresh-two-check/verified-fresh-two-summary.json, camera-diagnostics.I4Yixr,
pre-camera-restoration/verified-inactive-terminal-summary.json and both
completed read-only captures. Normal reboot evidence and frozen identity are
under `remote-video-ipc/verified-normal-camera-restoration.json`. The whole
REDCON/session-independence criteria remain unchecked until the missing
independent 2→1 direction is proved. No whole checkbox changes at this point.

### Reversible video-configuration retry experiment prepared — 2026-11-03

Source confirms separate daemon gRPC listeners and an existing worker path
that starts MAVLink before `GetWorkerConfigWithRetry`. The restored boot has
distinct video/MAVLink socket filesystem inodes **524/525**, daemon PID **2637**
and KVS PID **2656**, with the verified running hashes. Prepared a scoped
initialization fault under `tmp/issue-170/remote-video-ipc/`: stop the healthy
KVS worker for setup, hold only its daemon-owned video socket pathname under a
temporary sibling name, verify real inactive/terminal state, then start the
worker while its separate MAVLink socket remains available. Only after a new
data-only baseline is verified will the exact original video inode be restored
without a worker restart. At this preparation checkpoint, same-worker/cloud-run
telemetry continuity and actual 2→1/video receipt remain a live hypothesis;
the subsequent measured result is recorded below.

The first stop resets both WebRTC paths and is explicitly setup, not measured
video-only isolation. No camera driver, installed configuration, permission,
binary, capability or operational shadow is changed. Recovery checks the same
boot/daemon/hash and exact inodes, refuses replacement pathnames, and does not
depend on AWS access. Normal Office REDCON 4 is the fallback if exact local
restoration cannot be established. Final closeout still requires terminal
inventories and both cloud gates false.

Thirty-six actual remote-fragment cases pass against repository-local real
Unix sockets and proc/service doubles, covering changed identities/inodes,
stop failure, collision/symlink refusal and idempotent recovery. A separate
host-local socket check shows pathname withholding/restoration with unchanged
listener inode and an independent live connection. Those local tests do not
establish board/Linux/gRPC acceptance. POSIX/ShellCheck pass. The operator
procedure is prepared under the existing #170 independent-recovery scope;
no production code, new dependency, publication or automatic AWS action occurs.

### Independent video-config recovery passes — 2026-11-03

The first IPC setup stops KVS at **16:15:50 UTC**, then refuses before holding
the video socket. Read-only inspection at **16:19:10 UTC** finds no KVS process,
the unchanged daemon PID **2637**, both original socket inodes **524/525**, and
the camera still bound. The exact failing post-stop guard was not logged; a
transient PID-settling explanation is not established. No second stop is run.
Actual REDCON **3**/projection **2009**, a matching inactive observation, no
assignment/endpoint and the old VM's terminal state are verified first.

The reviewed continuation holds only video socket inode **524** at its temporary
sibling pathname, preserving the separate MAVLink socket **525**, then starts
KVS PID **3025** at **16:24:06 UTC**. This initial service stop/start is setup;
it is not the measured video-only recovery. The new actual REDCON **2**/
projection **2010** run is **1EF5165F-10D2-4C91-8807-B20C6AF3F345**, activation
**211F6D3E-9F13-407A-8D9C-DD94193A6183**, released image **4.0** VM
`microvm-c92972b7-eac3-317b-a9b3-89867a9f3bf8`. Its saved interval
**1793723019–1793726019** remains 3000 seconds. Twenty healthy telemetry samples
over **95.280 seconds** show **1676** received messages, zero video frames,
no video peer, and telemetry peer **17937230562716668**. QGC/attach stay
disconnected and the board reports fresh heartbeat, disarmed and no owner.

At **16:28:50 UTC** the operator restores only the original video socket inode.
The guarded command confirms KVS PID **3025**, daemon/boot identity and the
MAVLink socket remain unchanged; it restarts no service. Office and the actual
projection then report REDCON **1**/version **2011**. The cloud log first samples
nonempty H.264 receipt at **16:30:50.402 UTC**. Across **79** recovered samples
through **16:37:21.575 UTC** (**391.173 seconds**), frames increase **145→4749**
with advancing receipt metadata and connected/error-free video. This is actual
encoded-frame receipt, not merely the ready state. It bounds observed recovery
after restoration but does not measure the exact retry latency.

Throughout **157** healthy runtime samples spanning **782.335 seconds**,
MAVLink remains connected/error-free and messages increase **32→13540**. All
**157** telemetry peer diagnostics retain peer **17937230562716668** in the
connected state; the new video peer is **17937234442642885**. Run, VM,
activation, deadline and monotonically advancing runtime uptime remain
unchanged. No attachment or control is held. Seventy-one captured actual-1
samples independently show received cloud frames and the disarmed board.
SDK frame-drop warnings remain in the raw log; this acceptance demonstrates
independent receipt/recovery, not video quality or zero dropped frames.

The camera-only 1→2 case and this separate 2→1 config-retry case together
complete independent-media acceptance. They do not repair or reinterpret the
earlier fatal camera cleanup wait, nor the intermittent transport finding.
Whole-device DDEATH remains pending physical access. Forty-three guarded
remote-fragment cases and POSIX/ShellCheck validation support the procedure;
the acceptance above comes from the operator-run board and released cloud.

After the operator returns to actual REDCON **4**/projection **2014**, fresh
inspection confirms no assignment/endpoint, preserved activation history and
the tested VM **TERMINATED at 16:37:35.489 UTC**, before its **17:13:39 UTC**
deadline. Complete inventories across all five retained images contain zero
nonterminal VMs. The operator's disabled-return update finishes at
**16:41:18 UTC**. Fresh reads at **16:41:38–16:41:42 UTC** confirm both gates
false, controller automation disabled, the lifecycle IoT rule disabled,
concurrency one and unchanged released controller code. Both exact Scheduler
repair/watch configurations remain enabled and unchanged; only the ordinary
execution-role policy remains. Release **0.1.1**, image **4.0**, budget **3000**
and the same activation history are preserved. All five image inventories
contain zero nonterminal VMs (eleven listed terminal records). A second full
audit at **16:43:51–16:43:55 UTC**, starting **128.974 seconds** after the first
read set finished, confirms the same disabled/drained state and unchanged
history/schedules. The bounded read-only collector finishes with **360** samples
and **zero read errors**. No retained resource cleanup is performed.

Evidence is under `tmp/issue-170/remote-video-ipc/`: `setup.coEg2h`,
`inspect.XACJTi`, `inactive-check`, `continue-held.viZBnv`, `held-run.json`,
`held-check/verified-data-only-baseline.json`, `restore.S6yL0E`,
`recovery-check/verified-independent-recovery.json` and its saved runtime/peer
logs, `closeout/verified-inactive-read`, `closeout/post-disable`,
`closeout/repeated-disabled`, and the shared read-only capture
`remote-video/capture-20261103T161326Z`. `audit_recovery.py` validates the saved
live evidence without service calls or token access. No production code,
dependency, release artifact, permission or protocol changes were required.

### Remote assigned-record witness continuation — 2026-11-05

The operator committed the preceding Scheduler/acceptance changes as
`ba0103a8`, then requested more work without physical access. Fresh Frankfurt
reads retain release **0.1.1**, image **4.0**, budget **3000**, both ordinary
launch gates false, original controller/witness code, concurrency one and both
exact enabled Scheduler configurations. The real TBot remains actual REDCON
**4**/projection **2014**, with the same retained activation and no assignment
or endpoint. Complete inventories across all five images contain zero
nonterminal VMs.

Selected the existing synthetic assigned-record cases in the
[watch contract](constraints/agent-watch.md#synthetic-assigned-record-tests).
The released-image orphan case already passes; these separate cases will
check preservation despite synthetic media errors, an off-record grace and
an expired deadline while the record still says running. The temporary
untyped `testFixture` has no rig, hardware, credentials or signaling channels.
Its administrative records never replace real-device authorization or prove
physical DDEATH. No real Thing's operational shadow is written.

The operator's `isolation.Eg0P9r` pauses only controller repair and sets
concurrency zero. Independent reads at **08:58:15 UTC** confirm **133 seconds**
of drain beyond the controller's 120-second timeout, exact witness schedule
still enabled, actual REDCON 4, no assignment and zero nonterminal VMs.
A bounded read-only recorder starts at **08:59:15 UTC**. An inherited short
printed recovery path still named the prior batch; it is corrected to
`remote-assigned-watch/recovery.md`, whose frozen stack/history references
belong to this batch.

The operator's `known.iMzYV6` creates only the frozen untyped fixture
`agent-watch-170-20261105-f971f15f4722`, then launches image-4.0 VM
`microvm-c22f3019-59b4-3333-a534-3a4d61cc8f47` at **09:07:16.882 UTC**.
Its 600-second hosting cap is separate from any witness request. Version **2**
binds synthetic running record **watch-known-170-1793869636-f971f15f4722**,
activation interval **1793869636–1793870236**, with no endpoint and deliberate
independent media-error fields. The real device stays inactive. Preservation
beyond the orphan cutoff and later termination remain unaccepted at this
launch checkpoint.

Saved service evidence subsequently verifies preservation: **53** VM samples,
including `RUNNING` at age **264.040 seconds**, unchanged synthetic version 2
and media-error fields, eight recorded isolation samples, no witness watch
errors/termination request in the bounded window, and the real device's
shadow/history unchanged. This accepts synthetic assigned-record preservation,
not real runtime or session health.

The first audit incorrectly expected periodic runtime status from this
unsupported fixture and assumed its log-stream name. The source rejects the
unsupported profile before the periodic status logger, so no such stream is
expected. Also normalized the Update response's echoed null deletions to the
stored Get representation before comparing fixture state. These read-only
audit corrections changed no deployed behavior. The unnecessary log lookup
used the off-test time margin; no off transition is run after its remaining-time
guard closes. AWS later records **TERMINATED at 09:17:18.804 UTC**, reason
`MicroVM exceeded maximum lifetime.` This platform-cap termination is explicitly
not witness shutdown acceptance. The first case remains preservation-only.

Prepared a fresh bounded off-case attempt after this VM is terminal, reusing
only the same untyped fixture and preserving the complete first-case evidence.
Its version-conditional replacement requires the prior VM terminal and zero
nonterminal production inventory before another launch. The off and separate
deadline termination branches remain pending at this checkpoint.

The fresh `known.YMjsVM` launch succeeds at **09:19:13.137 UTC** as image-4.0
VM `microvm-5743b677-9018-3d49-8428-1870e4fcb990`, with a 600-second hosting
cap. Synthetic version **3** binds run/activation
**watch-known-170-1793870352-f971f15f4722**, interval
**1793870352–1793870952**. The old VM is already terminal, and its original
case files remain intact. The new audit verifies forty VM samples, `RUNNING`
at age **197.787 seconds**, seven isolation samples, unchanged fixture errors/
version and real TBot state/history, and zero controller events or witness watch
errors in the saved window. Runtime log absence is kept separate from this
assigned-record preservation result.

The operator's first off block `off.59n9ST` succeeds at **09:24:59 UTC**, version
**4**, preserving that run, VM, activation and deadline. The recorded first
`stopRequestedAt=1793870699` makes witness eligible at **09:26:59 UTC**. The
block reads back the full stored shadow after the partial Update response and
verifies identity/deadline preservation. It cannot repeat/reset the off time.
Grace preservation, exact witness request and terminal state remain to be
audited before accepting this off branch.

The off branch subsequently passes. The same VM is observed `RUNNING`
**101.924 seconds** after off with version 4 and its first stop timestamp
unchanged. Witness logs the exact-VM termination request at
**09:27:15.393 UTC**, **136.393 seconds** after off. AWS confirms
`TERMINATED` at **09:27:15.976 UTC**, **136.976 seconds** after off, reason
`Success.`, before both its unchanged **09:29:12 UTC** synthetic deadline and
the independent hosting cap. The saved audit includes **105** VM samples,
**18** isolation samples, zero controller events and witness watch errors,
unchanged fixture version/state after off, and unchanged real-device
shadow/history. No manual termination is requested. This accepts the assigned
off-record grace/termination branch on released image 4.0 with the independent
Scheduler watch; it remains a synthetic administrative test.

The separate `deadline.md` case is now released to the operator. It requires
the off-case VM terminal and launches a new 240-second synthetic activation
with an independent 600-second hosting cap, removing the old stop timestamp
under a current-version condition. Its result and final fixture cleanup/
controller restoration are still pending at this checkpoint.

The operator's `deadline.2mdj0Q` starts released image-4.0 VM
`microvm-b9e12ca4-f43d-34d3-8049-4abca9e0335a` at **09:32:36.595 UTC**.
Synthetic version **5** records run/activation
**watch-deadline-170-1793871155-f971f15f4722**, interval
**1793871155–1793871395**: exactly 240 seconds, expiring at **09:36:35 UTC**.
The independent hosting cap remains 600 seconds. The old stop timestamp is
absent and the fixture stays `running`/active with the same synthetic media
errors. Witness eligibility is **09:38:35 UTC**. No off transition is made
for this case.

Rotated the read-only recorder before the original bound could cut off this
new case. The first recorder finishes with **413 samples/zero read errors**;
the new capture begins at **09:33:15 UTC**, with the current VM running.
Each completed case audit pins its actual capture directory for reproducible
saved-evidence validation after rotation. Deadline grace/termination and the
final cleanup/restoration remain live requirements at this point.

The deadline branch also passes. The VM remains `RUNNING` **110.921 seconds**
after expiry with unchanged running/active version **5** and no off timestamp.
Witness logs the exact-VM termination request at **09:39:15.397 UTC**,
**160.397 seconds** after the persisted deadline. AWS records `TERMINATED`
at **09:39:15.919 UTC**, **160.919 seconds** after deadline and **399.324
seconds** after start, reason `Success.`, before the independent 600-second
hosting cap. The synthetic state/version remain unchanged. The audit contains
**86** VM samples and **15** isolation samples, no controller events or witness
watch errors, and unchanged real-device history/projection. No manual
termination is requested. This establishes deadline evidence independently of
an off-record transition.

Both recorders are stopped before fixture cleanup: **413** and **99** samples,
each with **zero read errors**. The operator is asked to run the reviewed
fixture-only cleanup, then restore controller concurrency/schedule only if
cleanup succeeds. The commands themselves check complete terminal inventories,
the exact untyped/uncredentialed fixture attributes, both resource absences and
the frozen controller/schedule configuration. Cleanup/restoration and a later
repeat inventory still require live verification at this checkpoint.

The operator completes `cleanup.8Eu5sy` at **10:12:42 UTC**, then
`recovery.accIRl` restores the original controller repair schedule at
**10:13:26.143 UTC**. Independent reads at **10:14:37–10:14:42 UTC** confirm
both the temporary registry Thing and its `agent` shadow return
`ResourceNotFoundException`, controller concurrency one, both exact original
repair/watch schedules enabled, disabled automation/lifecycle trigger and
ordinary execution-role policy only. Released controller/witness code and
their complete environments remain unchanged, with release **0.1.1**, image
**4.0**, budget **3000** and both ordinary gates false. The real TBot's
projection **2014**, shadow version/state and activation history are unchanged,
with no run or endpoint. Complete inventories across all five retained images
contain zero nonterminal VMs. A later repeat check is pending.

A second complete audit at **10:17:32–10:17:37 UTC**, starting **171.025
seconds** after the initial reads finished, confirms the same restored settings,
both fixture resources absent, unchanged real-device history/projection and
zero nonterminal VMs across all five images. The remote assigned-watch batch
is complete: preservation, off-record grace/termination and independent
deadline grace/termination pass on released image 4.0, and all temporary test
resources are removed. The earlier first VM's platform expiry remains
preservation-only evidence. No retained-resource cleanup, production code,
permission, release or artifact change is introduced.

Final evidence: `remote-assigned-watch/post-recovery/` and
`post-recovery-repeat/verified-restoration-summary.json`, both
`verified-fixture-absence.json` responses, `cleanup.8Eu5sy`, `recovery.accIRl`,
and `verified-final-closeout.json`. The saved-evidence audit checks both full
function environments as well as code, schedule configurations, history and
inventories. The implementing agent executes only needed read-only AWS calls,
local validation and documentation/tracker updates; mutations remain
operator-run. The acceptance record is uncommitted. #170 remains open with
six whole criteria checked: physical whole-device DDEATH and the earlier
camera/transport/credential-renewal findings remain separate.

Prepared commands and raw evidence are under
`tmp/issue-170/remote-assigned-watch/`; the current read-only preflight is under
`remote-resume-20261105/preflight`. Actual cloud mutations remain operator-run.
Fixture cleanup and exact controller restoration are reviewed before launch;
manual termination/platform expiry/failed run hooks cannot count as witness
acceptance. Full #170 acceptance and physical DDEATH remain open.

### Operator-run live cases

Run one case at a time. After each case, record its result and inspect it before
the next fault. The agent may inspect needed read-only AWS state; the operator
runs cloud mutations, attachment/token creation and all physical actions.
The [rollout runbook](constraints/agent-rollout.md) supplies the prerequisite
catalog/rig/witness/Office and legacy-trigger checks. Do not repeat legacy
cleanup or reset a real activation as part of acceptance.

1. **Normal budget, no attachment.** While TBot is verified inactive and safe,
   the operator updates both launch gates to true with budget 3000, retaining
   all image/controller/release parameters. Wait for stack completion and a
   directly observed inactive controller record. Activate normally through the
   existing lifecycle authority; do not manually launch a VM. Capture current
   shadows, complete image inventory, VM details and runtime logs at multiple
   times. Require exactly one authorized assignment, the released source/build,
   fresh authority, increasing telemetry and nonempty encoded video delivered
   to the operator, no attachment and no held control. An Office preview is a
   separate connection and cannot prove agent video receipt.
2. **Observation attachment, then explicit control.** QGC listens on UDP
   14550, remote `127.0.0.1:14551`, heartbeat enabled, duplicate auto-connect
   disabled. Record actual QGC version/settings and live telemetry. Run
   `just agent::attach tbot-8yzfgj --region eu-central-1` first. Record cloud
   attached state with no control and unchanged board peer count. End it before
   starting `just agent::attach tbot-8yzfgj 14551 --control --region eu-central-1`.
   Under a free lease, prove parameter names/values actually retrieved and
   perform the secured lifted arm/drive/disarm/re-arm flow. Record wheel motion
   directly, commands/acks and unchanged lease session/epoch through disarm.
   End with disarm and release. Each attach has a roughly four-minute client
   cutoff; the AWS token is requested for five minutes. A cutoff is not proof
   of AWS server-token expiry. Reopen explicitly for the next case.
3. **Contention/loss/recovery.** Record board owner/session/epoch and timestamps
   before and after each isolated case in the matrix. Closing just the QGC UDP
   link tests client inactivity; stopping `attach` tests attachment loss.
   Video-only loss must not be reported as a MAVLink loss check. Office's
   explicit takeover is permitted by its own client policy; agent takeover is
   never permitted. After loss, restore the path and observe no reacquisition
   before any new explicit control request. Existing physical fault procedures
   in the [local record](agent-physical-acceptance.md) are reference material;
   repeat them on this released cloud run with recorded board/cloud evidence.
   Confirm the exact scoped fault/restoration method before permission or
   network changes; do not broadly deny device/rig/witness AWS access.
4. **Events and stale endpoints.** The operator can invoke the released
   controller with recorded duplicate/delayed event hints naming this Thing;
   the controller must read current authority. Archive pre/post shadows, run
   identities and complete inventories. Retain the former endpoint/run identity
   during a real replacement and verify it cannot attach, hold control or
   restore a current endpoint. Do not replay shadow updates or forge device
   lifecycle to manufacture the result.
5. **Accelerated budget.** Disarm/release, take the device inactive and confirm
   terminal VM state. With no live run, set `ActivationBudgetSeconds=600`
   using an operator CloudFormation update; leave the released code unchanged.
   The controller must observe inactive before normal reactivation. Record
   `deadline-startedAt=600` and the actual remaining hosting duration from the
   persisted launch request. Well before expiry, disarm/release and manually
   terminate only the exact assigned VM while the device stays active; retain
   the service termination result. Its automatic replacement must use the
   same activation/start/deadline and only remaining time. Keep the device
   continuously active through expiry and at least two later repair passes;
   record authority loss, endpoint removal, actual terminal state and no new
   authorized run. Then perform a directly observed inactive→active transition
   and prove a new activation. Restore budget 3000 after the accelerated case
   and verify a later new activation has a 3000-second budget. Shortening the
   setting on an existing run is not this test. If startup/replacement consumes
   the available time, record the outcome and repeat with a reviewed larger
   value below 3000; do not silently reset the activation.
6. **Inactivity and death.** With safe disarmed control checks complete, exercise
   actual REDCON 3, REDCON 4 and device death separately. Confirm actual reported
   lifecycle and record authority loss and terminal VM state for each case.
   A command accepted for REDCON 2 does not prove actual 2; the board's derived
   state can remain 1. Use controlled video unavailability for the independent
   1↔2 check and a fresh real 2 activation. Never count `TERMINATING`, a stopped
   process, a shadow's stopped label or an API termination acknowledgement as
   terminal compute evidence.

For timed loss tests, retain before/after UTC timestamps and sufficient sample
frequency to measure the five-second client/board lease and fifteen-second
verification bounds. Minute controller samples alone cannot prove those
latencies. Runtime fencing can precede compute cleanup; witness's two-minute
grace/minute schedule is delayed repair and shares AWS dependencies. Preserve
that distinction in the result.

## Final compute, cost and operator closeout

End every physical phase disarmed, released and inactive. After the final case,
the operator restores budget 3000 and both launch switches false through
CloudFormation, preserving the release selection and activation history. Wait
for completion. Keep controller termination-only repair and the independent
witness watch enabled. Inspect each recorded VM with `get-microvm` until
`TERMINATED`; capture a complete paginated `list-microvms` for the dedicated
image across all versions, counting every nonterminal state. Repeat after a
later repair interval to detect restarts. Record final no-run/no-endpoint
shadow state. Verify actual board safe state; cached old `armed=false` is not
fresh confirmation after a transport outage.

Inventory stack resources and any retained legacy agent stack/resources.
The agent stack should have no dedicated VPC, NAT gateway, EIP, network
connector, ECS service or ECR repository. Managed public connectors do not
establish absence of old dedicated resources elsewhere. Record discovered
resource IDs and dependencies; cleanup remains manual and cloud-MCU networking
is outside this scope.

The operator reviews and acknowledges these remaining cost categories:

- S3 release/provenance objects and version history; retained buckets/old images.
- MicroVM image/snapshot storage and snapshot read/write operations, including
  minimum image-storage retention; usage/data transfer and image rebuild work.
- CloudWatch log ingestion/retention and controller/witness Lambda execution,
  scheduled/event/API traffic; IoT/KVS/WebRTC/TURN use while observing.

AWS documents running compute, snapshot operations/storage and data transfer
on its [Lambda pricing page](https://aws.amazon.com/lambda/pricing/) (reviewed
2026-11-02). Verify Frankfurt's current rates and actual retained resources in
the operator's billing view; this record makes no price estimate or zero-total-
charges claim. Zero running agent compute and no dedicated always-on agent
networking are the required outcomes, not zero AWS spend.

### Read-only resource/cost inventory — 2026-11-02

The complete Frankfurt reads under `tmp/issue-170/cost-inventory/` identify the
following current resources. Each image/version/VM response was inspected for
errors and an outstanding pagination token; all five image inventories are
empty. `verified-summary.json` records the capture interval and scope.

| Resource | Observed state | Acceptance meaning |
| --- | --- | --- |
| VPCs | Default VPC and `vpc-04e99652bcee39f08`, tagged `town-cloud-mcu`/`CloudMcuVpc` | No separate agent VPC; cloud-MCU VPC remains outside this issue |
| NAT gateways, Elastic IPs, network interfaces | None in the regional account inventory | No current agent networking allocation found |
| ECS/ECR | Only `town-cloud-mcu` ECS cluster; no ECR repositories | No companion cluster/repository found; cloud-MCU runtime is preserved |
| MicroVMs | Zero across `town-agent` and all four retained #165 probe images | Inactive baseline only; does not replace per-case terminal-state evidence after the released-cloud tests |
| Image versions | Three successful `town-agent` versions (1.0, 2.0, 3.0), two successful probe versions and two failed probe versions | Image/build metadata remains; successful snapshots are retained and must be reviewed for storage costs |
| S3 `agent/` prefix | Eleven object versions, 22,442,827 bytes, including 0.1.0 artifacts/receipt and two source-build ZIPs | Retained storage; excludes other buckets/prefixes and makes no whole-account storage claim |
| MicroVM logs | Production retention 14 days, reported storedBytes 627,142; probe retention seven days, reported storedBytes zero | Retention/ingestion and other Lambda log groups remain part of cost review; storedBytes is not a billing statement |

The historical companion CloudFormation stack is absent. The production image
uses the AWS-managed Internet egress connector. Retained
probe infrastructure/images/artifacts have not been deleted. No legacy or
cloud-MCU cleanup was performed. Operator acknowledgement of remaining costs
and manual publication/replacement remains pending, as does the final inventory
after physical acceptance.

Finally have the operator confirm the
[immutable publication/manual replacement flow](agent-release-publication.md):
new component version for changed artifacts/base rebuilds, successful selection
for later launches, running release/deadline preserved, immediate adoption only
after disarm/release/drain, and manual retained-resource review. Check off the
issue only after every matrix case has matching released-system evidence; leave
live failures open and explicit.
