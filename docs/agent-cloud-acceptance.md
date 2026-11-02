# Released cloud physical acceptance — #170

Status: **in progress; no released-cloud physical acceptance claimed**.
Selected on 2026-11-02 after #169 closed. This record covers the released
system, real TBot and QGroundControl. Historical
[#168 source-build checks](agent-cloud-build-validation.md) and automated tests
support diagnosis but cannot complete this gate.

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
| Identity | Exact GitHub release/source/build hashes, image version, controller code hash, Frankfurt stack and native attach executable; device/QGC/commands/logs | Baseline 0.1.0 only; final test release pending |
| Unattached startup | Normal inactive→active starts one authorized released VM; no attach process; increasing real telemetry and encoded video counters/metadata; observation only | Pending |
| REDCON 2/1 | Actual lifecycle 1→2 stops video alone, preserves MAVLink and run/deadline; 2→1 restores video; fresh actual-2 activation receives MAVLink only | Pending |
| QGC physical flow | `just agent::attach … --control`, real parameter retrieval, arm/drive/disarm/re-arm on secured lifted TBot; same session-owned lease across disarm/re-arm; final disarm/release | Pending |
| Contention | Office owns lease first: agent requests `takeover=false`, stays observer; explicit Office takeover of held agent control revokes it; no automatic regrant after Office release | Pending |
| Client/attachment loss | Separately measure QGC inactivity and attachment disconnect while holding control; board releases/disarms, healthy cloud observation continues; reconnect never reacquires | Pending |
| WebRTC/lease loss | Real MAVLink transport loss and real lease loss revoke control; returning transport stays observer; video-only fault preserves healthy telemetry, records independent error and recovers independently | Pending |
| Lifecycle/assignment evidence | Real denied/unavailable verification stops authority by fifteen seconds; stale endpoint/attachment is unusable; recovery cannot manufacture a new activation | Pending |
| Repeated/delayed events | Deliver duplicate/stale event hints to the released controller while inspecting current projection; one authorized run and unchanged deadline; old endpoint/runtime identity never restores authority | Pending |
| Duration/replacement | Accelerated activation expires at its saved deadline, replacement gets remaining budget, configuration/publication cannot extend it, continued activity never rolls over; verified inactive→active permits a new activation | Pending |
| REDCON 3/4/death | Each real lifecycle condition stops authority and yields terminal AWS VM state plus complete empty nonterminal inventory; no stale usable endpoint | Pending |
| Cost/operations | Inventory agent networking/legacy resources; operator acknowledges remaining storage/log/snapshot/API/event/data costs and immutable publication/manual disarm-and-drain replacement | Read-only baseline inventory recorded; operator review pending |

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

Review and commit/push the prepared changes manually, then build the clean
immutable `agent-v0.1.1` release through the
[publication workflow](agent-release-publication.md#build-and-release).
The operator publishes it with `just agent::publish 0.1.1`, using a reviewed
available managed base version. Preserve its printed evidence folder and verify
the selected image/controller checksums. **Do not reuse image version 3.0 as
evidence for the changed controller.** Record the newly returned image version.
Keep both switches false and the device inactive throughout this rollout.

Ordinary publication uses the existing CloudFormation template. It does not
install new template parameters. After successful publication, the operator
applies the verified **release's** `stack.yaml` to the existing disabled stack:

```sh
# Repository root, operator terminal. Retain this shell's evidence path.
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
```

Verify both gates remain false, the new parameter/env equal 3000, unchanged
released controller code hash and newly selected image, concurrency one,
controller minute repair enabled, witness independent minute watch enabled,
current real REDCON 4 and zero nonterminal VMs. Use a fresh stack read and
preserve every unrelated parameter during later operator changes. AWS update
failure is not permission to proceed.

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
