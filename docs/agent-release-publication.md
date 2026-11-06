# Immutable agent releases and publication

Status: #169's original publication was accepted on 2026-11-01; its historical
evidence is retained below. Released-cloud acceptance on 0.1.1/image 4.0 is
recorded in [#170's acceptance record](agent-cloud-acceptance.md). The
[#175 storage reset and retention](https://github.com/mparkachov/txing/issues/175)
passed live verification on 2026-11-06. Release 0.1.2/image 3.0 was selected,
with 0.1.1/image 2.0 retained. Both launch gates remained disabled.

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
the retained **unversioned** artifact bucket, generated IAM roles, logs, controller,
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

The discovered artifact bucket must have **never** had versioning enabled.
The publisher checks `GetBucketVersioning` before uploading and refuses both
`Enabled` and `Suspended`. Immutable release-specific keys and conditional
writes provide the required normal-publisher immutability without S3 object
versions. Existing versioned environments require the manual reset below;
removing `VersioningConfiguration` cannot make their existing buckets unversioned.

The command downloads the exact GitHub release, checks hashes and clean source
provenance, and conditionally uploads `agent/<version>/` objects to the stack's
artifact bucket. Existing objects must match byte for byte. It persists the
exact build input and derives its idempotency token from that input. Changing
the managed base or any other input at an existing version is rejected.
AWS's managed catalog can list base `2` while successful image metadata reports
`2.0`. Verification compares those equivalent forms without rewriting the
original request or its retry token; a different minor version is rejected.

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

### Retain the newest two successful builds

After verified selection, the same publication command inventories the dedicated
image and keeps the **two newest successful builds by AWS creation timestamp**,
normalized across time zones. The first fresh publication keeps one; later
publications keep two. Failed builds never occupy a retained slot. Retention
stops on pending/incomplete/foreign inventory, missing retained bundle objects
or a selected image outside that pair. Use one publisher per environment; a
changed selection aborts cleanup.

The publisher deletes older successful or failed versions and confirms each
version `DELETED` or absent before deleting any source objects. It then removes
unretained `agent/<MAJOR.MINOR.PATCH>/` bundles, including partial/failed uploads
and leftovers from interrupted cleanup. Each retained bundle includes
`microvm.zip`, `controller.zip`, `provenance.zip`, `hooks.json`, `stack.yaml`,
`release.json`, `SHA256SUMS`, `build-input.json` and `built.json`. Unrelated keys
and other images are outside cleanup. S3 requests contain at most 1000 keys;
per-key deletion errors cause failure. Inventories, the retention plan and
deletion responses remain in the printed evidence directory.

Build or selection failure does not start retention. After selection, a cleanup
error exits nonzero with **“Release selected, but retention is incomplete”**.
The selection is usable; rerun the same `just agent::publish <version>` with
the same managed base. The immutable receipt avoids another build, and current
inventories resume deletion even if an old image or some objects are already
gone. Deletion waits are bounded to five minutes per image version; a transient
error can require a later retry.

At this stage devices are assumed to run only the currently selected image
when publication starts. Keeping that predecessor alongside the new image
preserves those runs; handling older active versions is deferred. There is no
automatic run termination, draining, scheduled cleanup service or new Python
helper. GitHub releases and local acceptance evidence remain independent of
the two-build AWS storage window; S3 is not the historical evidence archive.

### Retry an interrupted publication

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
retry the same inputs; do not change tokens, overwrite objects or guess a
version from `latestActiveImageVersion`. Repair failed source/configuration with
a new agent version. Its GitHub artifact and local publication evidence remain
immutable; a later successful publication may retire the failed image/S3 bundle.

Existing running agents keep their stored release, exact launch request and
activation deadline. New launches use the selected release. Publication does
not drain, restart, extend an activation or enable launches. For immediate
adoption, the operator first disarms/releases on the secured lifted device,
disconnects clients, disables launches, waits for/executes the documented
manual drain and confirms zero nonterminal VMs. Publish, then manually restore
the previously approved activation switches and observe inactive then active.
Never delete the agent shadow or reset the activation clock.

## One-time reset to unversioned storage

This is the operator-approved fresh start for #175. Perform it with launches
disabled and zero nonterminal VMs. Existing agent image/artifact history is
discarded; GitHub releases and unrelated infrastructure are preserved. The
implementing agent prepares/reviews commands but must not execute AWS mutations.

1. Record the current template, parameters, resources, artifact bucket,
   dedicated image ARN, controller object/digest, activation history and repair
   schedules. Disarm/release, disconnect clients, keep the device inactive,
   disable both launch gates and verify complete terminal inventories. Build
   the new immutable GitHub artifact from reviewed committed source before
   disrupting AWS storage. The next prepared agent version is 0.1.2.
2. Update the existing stack with the reviewed new `agent/stack.yaml`. Preserve
   all parameters except the disabled gates and reset image selection:
   `ImageName=disabled`, `ImageVersion=''`, `Release=''`. Preserve the existing
   `ControllerBucket`/`ControllerKey` during this update. New logical resource
   `ReleaseArtifacts` creates a fresh bucket, and `ArtifactBucket` points to it;
   the old `Artifacts` bucket is retained outside the template. The build role
   now reads the new bucket. Preserve unrelated resource identities and
   activation history. The existing `ImageConfigured` condition temporarily
   disables controller repair while `ImageName=disabled`; first publication
   re-enables that same schedule. The independent witness schedule stays
   enabled. `just agent::deploy` is for initial stacks and must not be used here.
3. With all VMs terminal, manually delete the old dedicated image through
   `delete-microvm-image` and wait for `DELETED` or confirmed
   `ResourceNotFoundException` from `get-microvm-image`. Whole-image deletion
   removes its versions and avoids deleting the last version separately.
   Keep the old bucket/controller ZIP until the first fresh publication selects
   its replacement. The image name must remain the normal
   `<environment-stack>-agent` name used by witness. A short maintenance interval
   without that image is expected. Do not invoke repair functions manually or
   reset device shadows.
4. Check the new bucket and publish the new GitHub release using the ordinary
   command. Disabled `ImageName` makes the first publication create the image
   afresh. Verify exact successful image/controller selection, new controller
   bucket/key and digest, disabled gates, budget 3000, preserved history/schedules
   and zero nonterminal VMs. Inspect the retention plan and final image/object
   inventories. One image/bundle is correct after this first publication; two
   remain after the second and third.
   For #175 live validation, the prepared sequence republishes the immutable
   GitHub 0.1.0 and 0.1.1 inputs into the new bucket, then publishes 0.1.2.
   This exercises deletion of the first image and its complete bundle while
   ending with 0.1.1 and 0.1.2. All builds are fresh; none of the old AWS
   artifacts are copied. Publication always uses the deployed new template,
   including when an earlier archive contains an old template.
5. After old-image deletion was confirmed and no current stack/controller/image
   version references the retired bucket, manually empty and delete that exact bucket. In the
   S3 console choose **Empty**, deleting all object versions and delete markers.
   `aws s3 rm --recursive` alone is insufficient for a versioned bucket. Verify
   no versions/markers remain before deletion; complete or abort multipart
   uploads if present.

Useful operator checks, with bucket names resolved from saved old/current stack
outputs rather than guessed:

```sh
# Never-enabled storage returns no Status; Suspended is not acceptable.
aws s3api get-bucket-versioning --region eu-central-1 --bucket "$new_bucket"
aws lambda-microvms list-microvm-image-versions --region eu-central-1 \
  --image-identifier "$image_arn" --page-size 50 --output json
aws s3api list-objects-v2 --region eu-central-1 --bucket "$new_bucket" \
  --prefix agent/ --output json

# After manual S3-console Empty, including every version and delete marker:
aws s3api list-object-versions --region eu-central-1 --bucket "$old_bucket" \
  --output json > "$reset_dir/old-versions-after-empty.json"
jq -e '(.Versions//[]|length)==0 and (.DeleteMarkers//[]|length)==0 and
  (.NextToken//.NextKeyMarker//null)==null' "$reset_dir/old-versions-after-empty.json"
aws s3api list-multipart-uploads --region eu-central-1 --bucket "$old_bucket"
# Review the exact bucket and absent references before this operator action:
aws s3api delete-bucket --region eu-central-1 --bucket "$old_bucket"
```

AWS does not allow a versioning-enabled bucket to return to the unversioned
state. Retained versions remain until explicitly removed, even after versioning
is suspended. See [S3 versioning states](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html)
and [emptying a bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/empty-bucket.html).
CloudFormation creates the replacement; deleting the old physical bucket first
would leave an existing stack resource missing. No artifact migration, dual
publishing or compatibility path is supplied.

## IAM, retained costs and base-image maintenance

The publishing principal needs GitHub release read access; CloudFormation
describe/update/use-template and deployment IAM permissions; conditional S3
PutObject/GetObject on the discovered bucket; MicroVM image create/update/get,
`lambda:ListMicrovmImageVersions` for interrupted-build recovery, and
managed-version listing; GetFunctionConfiguration; `iam:PassRole` on the
discovered build role; and `lambda:PassNetworkConnector` on the managed Internet
egress connector. Initial deployment additionally needs the stack's S3/IAM/log,
IoT/EventBridge and Lambda permissions. Resolve role ARNs from stack outputs;
do not assume generated physical names. Image builds use the stack build role;
device sessions use the separate execution role. Attachment permission remains
separate and restricted to trusted humans as described in the replacement
runbook. Keep TLS verification enabled.

Retention additionally requires `s3:GetBucketVersioning`, `s3:ListBucket` and
`s3:DeleteObject` on the discovered artifact bucket and
`lambda:DeleteMicrovmImageVersion` on the dedicated image. Do not add publisher
permissions to controller, witness or device execution roles. The one-time
manual reset separately needs whole-image deletion, CloudFormation update,
old-bucket object-version deletion and bucket deletion permissions.

Monitor managed-base availability and AWS notifications. Current AWS guidance
describes AVAILABLE, then DEPRECATED (60 days), EXPIRING (30 days, no new
builds), EXPIRED (no builds/runs), and possible immediate RECALL. Rebuild and
publish a new component version on a supported managed base before expiry;
also update/revalidate the pinned container base and packaged RPM/native
dependencies for security fixes. A managed-base version and a Dockerfile
container digest are distinct inputs. See
[AWS image lifecycle and patching](https://docs.aws.amazon.com/lambda/latest/dg/microvms-images.html).

Retained buckets, MicroVM images/snapshots,
build activity, CloudWatch logs, controller/watch calls, event delivery, traffic
and attachment/API usage can remain billable at zero running agents. Logs have
14-day stack retention. Operator-run publication now prunes old image versions
and their release bundles after selection, keeping the newest two successful
builds. Retired versioned buckets and their noncurrent objects still incur
storage until manual cleanup completes. Inactive image versions retain
snapshots; changing `ACTIVE` to `INACTIVE` does not delete them. Minimum storage
billing and service deletion latency can outlast a publication. Preserve
GitHub/local acceptance evidence independently. No scheduled cleanup, rollback
framework, NAT, ECR push or ECS task definition is added.

## Acceptance evidence and scope

For #175, three operator publications of immutable releases retained one,
then two, then two successful images. The third publication confirmed image
1.0 was deleted before removing its 0.1.0 bundle. The final audit checked
all 18 object checksums, the selected controller digest, and that the new
bucket had no versioning status. The operator emptied and deleted the retired
versioned bucket after all image and controller references were removed.
Both repair schedules remained enabled, and no nonterminal VMs remained.
The [release workflow](https://github.com/mparkachov/txing/actions/runs/42097748438)
passed 36 publication tests, including build and selection failure and retry
after partial cleanup. These failure cases used mocked AWS responses.

The final record below maps #169 to native/ARM64 tests, packaged execution and
repeatability, immutable GitHub/S3 identities, actual AWS image build and
CloudFormation selection, and the deployed controller digest. Failed-build
selection fencing and running-release preservation are covered by automated
tests; the two observed operator publication failures also retained the prior
selection. No deliberate failed AWS snapshot build or live publication during
an active device-control session was induced. Do not treat the tests as those
live experiments. #170 owns released physical motion, parameters, contention,
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
README/status documentation closeout. That manifest identifies this historical
candidate; later CI/test and publication-client fixes are recorded below.
Runtime/controller application sources stayed unchanged. The subsequent clean
release used its own committed revision. The accepted #167 timeout limitation
remains unresolved.

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
cleanup or commit was performed by the implementing agent. The later clean
GitHub release and completed operator-run AWS publication are recorded below.
Released-cloud physical/lifecycle acceptance remains the separate #170 scope.

### First GitHub workflow attempt

The operator dispatched [run 41293017611](https://github.com/mparkachov/txing/actions/runs/41293017611)
from `main` at `ba73d72a2116d0ae374bf6ce4bb6a9ca1ce8c3d8`. It failed before
ARM64 compilation/publication: direct unittest invocation encountered a fresh
checkout with no `tmp/` parent for its temporary directories. Test setup now
creates that repository-local parent idempotently. An exported source tree
without `tmp/` reproduces all ten original errors; applying the fix makes the
same ten-case command pass. Before/after evidence is under
`tmp/issue-169-fresh.W4aHOH/`. The successful clean GitHub rerun below contains
this test-only fix; the failed attempt created no immutable release or AWS
publication evidence.

### Verified GitHub release — 2026-11-01

The operator's [run 41293378129](https://github.com/mparkachov/txing/actions/runs/41293378129)
succeeded on `main` at `eb17bdcd48efbbd910738d851c62149d906b9254` and published
[agent-v0.1.0](https://github.com/mparkachov/txing/releases/tag/agent-v0.1.0)
at 10:36:56 Europe/Berlin (09:36:56 UTC). The downloaded archive's hash matches
GitHub's asset digest. Its manifest is `clean=true`, names that same commit and
matches both executables' build identity. All outer, nested and source-archive
checksums pass; the extracted executables are executable ELF64 AArch64 files.
The packaged source includes the accepted #167 physical record and limitation.

The successful CI steps cover the ten publication tests, full ARM64 build and
eight CTests, repeat packaging comparison, provided.al2023 dependency/startup
checks and packaged help/POST ready execution. Downloaded build evidence and
the shipped CTest/provenance files agree with the release manifest. This
establishes the immutable GitHub artifact; it does not establish AWS image
creation, S3 publication or CloudFormation selection.

| Released identity | Value |
| --- | --- |
| Source manifest SHA-256 | `9d04da9ea50641b978dc2df15271dc32bb850b28f7f7e17d5e40b378a67517a6` |
| Outer archive SHA-256 | `b54837658d396d813f14ffce3266a001d889e9d6c93c90bafe0b2776f11538fa` |
| MicroVM ZIP SHA-256 | `dbaf9a0456ba455cda30a52ad5efa3a7aa4666b302ecb0bdb4560bf5bb36aaad` |
| Controller ZIP SHA-256 | `2173c3565b33141e71773131d348d4c5324012cac6ac5a10e5ba487fb3c7ddb1` |
| Provenance ZIP SHA-256 | `3b7d22bdeb5ac2f03a6bc1191a0080e54d69c8d405e7ec537c77454069a48afd` |

Exact GitHub metadata, released archive, downloaded build evidence, extracted
content and checksum results are under `tmp/issue-169-release.LBFOGI/`. That
release is distinct from the earlier dirty-tree candidate. The operator then
published this exact artifact to the existing AWS stack as recorded below;
initial deployment was not repeated.

### First AWS publication attempt — verification failure

The operator ran `just agent::publish 0.1.0` with managed base input `2`.
Evidence is `tmp/agent-publish-0.1.0.zl9x47/`. S3 PutObject responses contain
VersionIds and SHA-256 checksums matching every released artifact and the
immutable build input. AWS built `town-agent` image version `3.0` from
`s3://town-agent-artifacts-7huc6mggtip3/agent/0.1.0/microvm.zip`; its recorded
state is `SUCCESSFUL`/`ACTIVE` at 10:56:18.674 Europe/Berlin. Metadata reports
managed base `2.0`, for the requested base `2`.

The publication client compared those strings exactly and exited 1 before
writing its successful-build receipt or attempting CloudFormation selection.
The operator confirms that terminal failure. The prior stack snapshot has
image version `2.0`, empty Release and both activation switches false; this
attempt did not send a selection update. It is not a failed AWS image build.

The local client now canonicalizes only the integer/`.0` base-version forms
for verification. The new regression failed before this repair and passes
afterward, along with all eleven publication cases and ShellCheck. The same
predicate was replayed against the actual AWS response and passes. Wrong-base
responses remain rejected. No runtime/controller artifact was rebuilt or
overwritten by this client-only fix.

Retry from the updated working tree using the original base input `2` and
the same release. That preserves the immutable build input and client token
`63f480687a9547e24d94170256f9d24985867839cff82b5b50a9acf10374e037`.
The retry must verify the actual returned image version and selected stack;
do not infer selection from this successful build alone. Keep launches
disabled and retain the retry's printed evidence directory. The implementing
agent executed no AWS command. The successful later selection and controller
digest evidence are recorded below.

### Rejected API replay — existing-build recovery repair

The operator's next attempt, `tmp/agent-publish-0.1.0.hgO9Wl/`, failed with
`ValidationException: The provided clientToken was used with different request
parameters`. Its saved build input is byte-for-byte identical to the first
attempt and produces the same token. Both before snapshots retain image `2.0`,
empty Release and false activation switches. No selection update was sent.
The saved files do not identify the service-side comparison that rejected the
replay, so changing the token is not used as a workaround.

The local publication client now performs the exact-configuration inventory
recovery described above before submitting a build when its receipt is absent.
The new rejected-replay regression failed before the repair and passes
afterward. All fifteen publication cases pass, including initial missing-image
creation, no resubmission after an interrupted response, duplicate/conflicting
version rejection, and fail-closed inventory errors. ShellCheck passes. The
actual recovery filter independently matches the recorded AWS image `3.0` to
the original immutable input; that result is saved in
`tmp/issue-169-recovery-audit/matched-real-build.json`. Before/after test logs
are `tmp/issue-169-replay-before.log` and `tmp/issue-169-recovery-after.log`.

The successful retry below uses base input `2` and release `0.1.0`, recovers
image `3.0` from live inventory and revalidates that exact version before
receipt/CloudFormation selection. No published artifact was changed, and the
implementing agent performed no AWS execution or commit.

### Accepted AWS publication and final #169 audit — 2026-11-01

The operator's completed invocation recorded
`tmp/agent-publish-0.1.0.sev42S/`. It recovered the existing image version `3.0`
without a new build submission, verified `SUCCESSFUL`/`ACTIVE` plus parent
image state `UPDATED`, wrote the immutable successful-build receipt and
completed CloudFormation selection. The GitHub archive and every component
hash still match the released identities above. Its build input is byte-for-byte
identical to the first attempt, with base `2` and the same token.

The selected stack snapshot is `UPDATE_COMPLETE`: `Release=0.1.0`,
`ImageVersion=3.0`, `ImageName=town-agent`,
`ControllerBucket=town-agent-artifacts-7huc6mggtip3`, and
`ControllerKey=agent/0.1.0/controller.zip`. `AutomationEnabled=false` and
`PrerequisitesConfirmed=false` were preserved, as were every other parameter
outside the release/image/controller selection. The stack's last-update
timestamp is 11:26:45.963 Europe/Berlin. The active controller's last-modified
timestamp is 11:26:59, with `LastUpdateStatus=Successful` and runtime environment
release `0.1.0`, image `3.0`, automation `disabled`.

The deployed controller CodeSha256 is
`IXPDVlszFB5xdzEx00jUxTJAEsrGrFoQ5bpIf7PH3bE=`, independently matched to the
released ZIP's SHA-256
`2173c3565b33141e71773131d348d4c5324012cac6ac5a10e5ba487fb3c7ddb1`.
The successful receipt at `agent/0.1.0/built.json` has S3 VersionId
`WZ_KKlkC43UPE5_qQIvHXBU.cZQU1O_h`; its returned SHA-256 matches the saved
receipt bytes. The local independent verification summary is
`tmp/agent-publish-0.1.0.sev42S/verified-summary.json`.

| #169 requirement | Authoritative evidence |
| --- | --- |
| Immutable ARM64 runtime/controller, provenance and dependencies | Clean `agent-v0.1.0`, GitHub run 41293378129, verified outer/nested/source checksums, ELF identities, packaged startup/linker evidence and exact S3 artifact checksums/VersionIds |
| Separate initial infrastructure | `agent::deploy`, disabled-default `agent/stack.yaml`, initial #168 deployment evidence and the initial-install runbook; ordinary publication used the existing template |
| Successful-only publication and failure fencing | Actual successful AWS image `3.0`, immutable receipt, `UPDATE_COMPLETE` selected snapshot and matching controller digest; both failed attempts and the successful retry begin with unchanged prior image `2.0`/empty Release; FAILED/inactive/wrong-identity paths pass automated checks |
| Existing-run version/deadline preservation | Native and ARM64 reconciliation regression retains the original release, request, run and activation deadline across a new release selection; the publisher has no run/terminate/shadow-write calls; manual disarm-and-drain instructions are explicit |
| Approved implementation boundary | One shared C++ build with CMake/Just/POSIX orchestration; no new Go/Python production helper or duplicate controller Dockerfile |
| Packaged execution, repeatability and real publication | Eight native CTests, eight release ARM64 CTests, clean CI packaged help/POST-ready and archive equality; actual operator S3/image-build/selection evidence |
| Operational documentation | This runbook and the replacement runbook cover base lifecycle, provenance, retained costs, credentials/IAM, legacy retirement, activation gates and forward deployment |
| Physical prerequisite and execution gates | Accepted #167 physical record/timeout limitation is included in the released source; AWS publication was operator-run, and the implementing agent made no commit, AWS call, device/flashing action or legacy cleanup |

All fifteen final publication tests and ShellCheck pass. The current local
publication-client repairs and documentation closeout remain uncommitted for
operator review; they do not replace the immutable released binaries. No live
in-flight version-retention or deliberately failed snapshot-build experiment is
claimed. The existing #167 intermittent native transport timeout remains
unresolved. Final released-cloud physical/lifecycle/cost acceptance belongs to
#170. Stop at #169 and keep both launch switches false until that next goal is
selected; no further #169 deployment or cleanup is required.
