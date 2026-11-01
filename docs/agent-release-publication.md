# Immutable agent releases and publication

Status: #169 implementation prepared; local ARM64 candidate validation passes.
Immutable release and operator-run publication acceptance are pending. Keep the
existing launch switches disabled until the release gates are recorded.

An `agent-vX.Y.Z` GitHub Release contains
`txing-agent-release-linux-arm64.zip`. The archive holds `microvm.zip`,
`controller.zip`, `provenance.zip`, the hooks and initial CloudFormation
template, `release.json` and `SHA256SUMS`. The same component version covers
the runtime and controller; it is independent of the shared Go `lambda` stream.

`microvm.zip` contains a Dockerfile and the **prebuilt** ARM64 application and
native libraries. AWS copies those bytes and validates linking/startup; it does
not fetch dependencies or compile the release again. The container base is
pinned by digest. Snapshot-safe OpenSSL is packaged with the application, and
the controller includes its non-glibc dependencies for `provided.al2023`.
Container glibc compatibility is checked in the exact packaged runtime; the
controller is loaded and started in a recorded digest of `provided.al2023`.
The service-managed MicroVM base is a separate version recorded at publication.

Source revision/content hashes, the KVS/AWS SDK and other native pins, recursive
AWS CRT revisions, build/runtime RPM inventory, ARM64 ELF headers, CTest results,
linker checks and controller startup checks accompany the artifacts. The source
archive includes the local physical acceptance record. #167 closed on
2026-10-28 with the operator's acceptance of the documented intermittent native
transport timeout; publication does not claim to repair it. See the
[physical record](agent-physical-acceptance.md#timeout-record-and-closure-decision--2026-10-28)
and [#168 source-build evidence](agent-cloud-build-validation.md).

## Build and release

Review changes and manually commit/push before creating a production release.
No recipe commits, pushes, bumps versions, flashes hardware, or publishes to
AWS as part of an artifact build. To prepare the first release, the agent
version is `0.1.0` in `release/versions/agent`. Before any later changed artifact,
bump **agent**, including for dependency or container/managed-base rebuilds:

```sh
just release::bump agent <new-version>
# Review, commit and push manually, then dispatch the chosen branch.
just release::build agent <branch>
```

For the first release, make `.github/workflows/release-agent.yml` available on
the repository's default branch through the normal reviewed commit/push or
merge process before dispatching. GitHub requires that default-branch copy
for `workflow_dispatch`, even when `--ref` selects a different build branch.
A workflow existing only on a new feature branch cannot be dispatched yet.
See [GitHub's manual workflow requirements](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

The manual GitHub workflow uses native ARM64 and the same
`just agent::release-package` recipe as local validation. CI explicitly selects
Docker; workstation builds default to `nerdctl.lima` with the existing engine.
The workflow checks the component's version/tag and creates one immutable
GitHub artifact. It has no AWS credentials and performs no AWS deployment.
Generic existing release metadata tooling only reads/bumps the new component
version; agent build/publication orchestration stays in CMake/Just/POSIX shell.

For local validation:

```sh
nerdctl.lima info
just agent::release-package
```

Retain the printed SHA-256, work directory and its build/packaged-runtime logs.
Packaging runs twice over a frozen tested build and requires identical archive
bytes, with normalized order/timestamps and no host UID/GID ZIP fields. The
exact packaged image is then built and run without networking/credentials:
help and the pre-snapshot ready hook must pass. This establishes repeatable
packaging, not bit-for-bit recompilation across different compilers or RPM
repository states. RPM inventories record those inputs; future rebuilds get a
new component version and cannot replace the previous release. A dirty local
tree can produce a validation candidate under `tmp/agent-releases/candidates/`,
marked `clean=false`; publication rejects it. Clean local output refuses
different bytes at an existing release version.

## Initial infrastructure, once

Complete the [initial replacement runbook](constraints/agent-rollout.md), including
inventory, disabled old triggers, disarm/release, zero old tasks and manual
resource/shadow cleanup. Preserve cloud MCU networking. Complete the catalog,
rig, witness and Office prerequisites there. #168's bounded test left
`town-agent` image 2.0 installed, launches disabled and zero nonterminal VMs;
an already working stack is updated through publication, not recreated.

For a new environment, download the selected GitHub archive, verify
`SHA256SUMS` and `release.json`, and upload `controller.zip` to an existing
bootstrap bucket under an immutable key, using conditional S3 PutObject
(`--if-none-match '*'`). Supply that existing object, then run as the operator:

```sh
export TXING_AGENT_CONTROLLER_BUCKET=<existing-bootstrap-bucket>
export TXING_AGENT_CONTROLLER_KEY=agent/<version>/controller.zip
just agent::deploy
```

The recipe verifies concurrency headroom, refuses an existing stack and creates
CloudFormation with both acceptance/launch switches false. The stack creates
the retained versioned artifact bucket, generated IAM roles, logs, controller,
managed attachment policy and initially disabled triggers. Never work around the controller's
reserved concurrency of one. Failed `ROLLBACK_COMPLETE` initial stacks and
retained buckets require the manual handling in the replacement runbook.

## Ordinary publication

Use one publisher per environment at a time. Authenticate the AWS CLI and `gh`
as the operator, with no credentials in the package. The root project AWS
environment selects the established profile/stack; every AWS call in this
workflow explicitly uses `eu-central-1`. Inspect current managed versions:

```sh
aws lambda-microvms list-managed-microvm-image-versions --region eu-central-1 \
  --image-identifier arn:aws:lambda:eu-central-1:aws:microvm-image:al2023-1
export TXING_AGENT_BASE_IMAGE_VERSION=<reviewed-AVAILABLE-imageVersion>
just agent::publish <version>
```

The command downloads the exact GitHub release, checks hashes and clean source
provenance, and conditionally uploads `agent/<version>/` objects to the stack's
artifact bucket. Existing objects must match byte for byte. It persists the
exact build input and derives its idempotency token from that input. Changing
the managed base or any other input at an existing version is rejected.

The first publication creates the dedicated image named after the agent stack;
later publications update that same image. The build uses explicit ARM64,
4-GiB baseline, snapshot hooks and Internet egress, with no device identity or
live sessions in the snapshot. The baseline matches the accepted source-build
configuration; size/cost acceptance remains #170. Do not change the dedicated
image name during ordinary publication: controller/watch inventory and IAM
scope depend on it.

Publication waits up to an hour for the **returned version** to be
`SUCCESSFUL`/`ACTIVE`, verifies artifact/base identity and the parent image's
runnable state, then writes an immutable successful-build receipt. Failed,
inactive, uncertain or timed-out builds do not change selected stack parameters.
A failed image update can still make the service's parent image unavailable
for subsequent launches; inspect its state and publish a new repaired version.
Retaining the previous selection does not override AWS service availability.

Only after success does CloudFormation select the version and matching
controller object using the existing template. All other parameters, including
`AutomationEnabled` and `PrerequisitesConfirmed`, retain their previous values.
Publication detects an intervening stack change and stops for a retry. The
command waits for the stack update and compares deployed controller CodeSha256
with the exact release ZIP. The retained work directory contains inputs,
responses, selected parameters and artifact identities. It creates no device
activation, token, attachment or VM and never changes agent shadows.

An interrupted publication can be rerun with the same version/base: matching
objects are retained, the same request token is reused, and a successful
receipt avoids another build. After a prolonged ambiguous API result, inspect
image versions and their exact artifact/base before retrying; AWS token
retention is finite. Do not change inputs, overwrite objects or guess a version
from `latestActiveImageVersion`. Failed releases remain immutable evidence;
repair source/configuration with a new agent version.

Existing running agents keep their stored release, exact launch request and
activation deadline. New launches use the selected release. Publication does
not drain, restart, extend an activation or enable launches. For immediate
adoption, the operator first disarms/releases on the secured lifted device,
disconnects clients, disables launches, waits for/executes the documented
manual drain and confirms zero nonterminal VMs. Publish, then manually restore
the previously approved activation switches and observe inactive then active.
Never delete the agent shadow or reset the activation clock.

## IAM, retained costs and base-image maintenance

The publishing principal needs GitHub release read access; CloudFormation
describe/update/use-template and deployment IAM permissions; conditional S3
PutObject/GetObject on the discovered bucket; MicroVM image create/update/get
and managed-version listing; GetFunctionConfiguration; `iam:PassRole` on the
discovered build role; and `lambda:PassNetworkConnector` on the managed Internet
egress connector. Initial deployment additionally needs the stack's S3/IAM/log,
IoT/EventBridge and Lambda permissions. Resolve role ARNs from stack outputs;
do not assume generated physical names. Image builds use the stack build role;
device sessions use the separate execution role. Attachment permission remains
separate and restricted to trusted humans as described in the replacement
runbook. Keep TLS verification enabled.

Monitor managed-base availability and AWS notifications. Current AWS guidance
describes AVAILABLE, then DEPRECATED (60 days), EXPIRING (30 days, no new
builds), EXPIRED (no builds/runs), and possible immediate RECALL. Rebuild and
publish a new component version on a supported managed base before expiry;
also update/revalidate the pinned container base and packaged RPM/native
dependencies for security fixes. A managed-base version and a Dockerfile
container digest are distinct inputs. See
[AWS image lifecycle and patching](https://docs.aws.amazon.com/lambda/latest/dg/microvms-images.html).

S3 current/noncurrent versions, retained buckets, MicroVM images/snapshots,
build activity, CloudWatch logs, controller/watch calls, event delivery, traffic
and attachment/API usage can remain billable at zero running agents. Logs have
14-day stack retention; artifacts have no automatic deletion. Review usage and
manually retire unreferenced releases/images only after inventory, according to
the operator's retention policy. Do not remove objects referenced by current
selection, running/reserved requests, acceptance evidence or retained images.
No cleanup, rollback framework, NAT, ECR push or ECS task definition is added.

## Acceptance evidence still required

Record fresh native/ARM64 tests, packaged linking/help/ready checks and identical
archive hashes. Then record the operator's GitHub release/commit, archive and
S3 checksums/versions, managed and container bases, exact successful image
version, hook logs, stack update and deployed controller digest. Exercise an
operator-selected build failure and prove the previous selection is intact.
Record any existing run retaining its release/deadline during publication, or
state explicitly that no run existed. Do not enable/move hardware merely to
fill that row. #170 owns released physical motion, parameters, contention,
faults, accelerated duration/replacement/no-rollover and final cost acceptance.

## Local candidate validation — 2026-11-01

The native macOS rebuild passes all eight CTests. The existing 25 Python
host/CLI/schema checks and the expanded ten-case CMake/publication suite pass;
eight generic release-tool checks, ShellCheck and actionlint also pass. The
publication suite executes the actual POSIX recipe with mocked CLI endpoints;
it establishes local behavior, not AWS acceptance.

After the operator started Lima, `just agent::release-package` completed a
fresh native Linux ARM64 build. All eight Linux CTests passed. The controller
loads in the recorded `provided.al2023` digest, and its extracted ZIP was
independently checksum-checked, loaded and started to its expected missing
Lambda-runtime-API diagnostic. The packaged MicroVM image builds and executes
help and the POST ready hook with networking disabled. Ready reports no runtime
identity, credentials or device sessions initialized. The first probe attempt
used GET and failed against the POST-only hook; the corrected final recipe and
its complete rebuild pass. Two independent archives from the final frozen build
compare byte for byte.

This is an **unpublished dirty-tree validation candidate**, not a production
release. The final source manifest verified against the working tree before
README/status documentation closeout; runtime, build and test sources remain
unchanged. The GitHub workflow must build a clean committed revision before
operator publication. The accepted #167 timeout limitation remains unresolved.

| Identity | Value |
| --- | --- |
| Candidate version | `0.1.0`, `clean=false` |
| Base source revision | `9ba52fa8dc40cc68f270f50d0025f76c6b3a24bf` plus frozen dirty source manifest |
| Source manifest SHA-256 | `44736da953b1848f244fd4c95636986bb3e3c320c0d3b799cafdf341d53551d6` |
| Outer archive SHA-256 | `cba5d5d517db32bb99528b37143e4866813caba3661591903b0f8f3dc8fd5c0d` |
| MicroVM ZIP SHA-256 | `c643cf98460fe3cbcc46d7389b03791e83f40953ef243b8c8d6ca9de5eb7914d` |
| Controller ZIP SHA-256 | `62d49ada8da4c5ed53b52f6661db9151b033a3a038185377783622b7aefa26ee` |
| provided.al2023 digest | `sha256:2dc0f1f26731018b369932201d1dac295edd1730d1280f194486ae093ac39798` |

The candidate is under
`tmp/agent-releases/candidates/0.1.0/<outer-sha>/txing-agent-release-linux-arm64.zip`.
Exact build, source manifest, two packages, CTests, linker/startup/ready results
and independent extracted-controller checks are under
`tmp/agent-release-0.1.0.9PJ1De/`. Native/full-suite, expanded publication and
final ARM64 recipe logs are `tmp/issue-169-tests.log`,
`tmp/issue-169-publication-tests.log` and
`tmp/issue-169-arm64-package-final.log`.

No GitHub release, AWS execution, device control, firmware action, legacy
cleanup or commit was performed by the implementing agent. #169 stays open
for the clean release and actual operator-run publication/failure/selection
evidence; #170 is not started.
