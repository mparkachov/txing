# Retire the issue-165 AWS probe

Inspected on **2026-11-05**, AWS account `453102798330`, profile `mayor`,
region **eu-central-1**. **Operator cleanup is complete and independently
verified.** The probe stack reaches `DELETE_COMPLETE` at
**12:39:06.434 UTC / 13:39:06.434 Europe/Berlin**. The assistant performs only
read-only AWS inspection. Scope covers the Frankfurt probe and account-wide
S3/IAM name discovery, not every AWS Region.

#165's acceptance record verified termination of all seven experimental runs.
Images, source ZIPs, stack and logs were explicitly retained for retries and
diagnosis. The inventory below records that infrastructure before removal.

## Verified completion

The operator reports the final verification output, and independent reads
confirm all expected results:

| Check | Verified result |
| --- | --- |
| Captured probe stack ARN | `DELETE_COMPLETE`; all four owned resources also have `DELETE_COMPLETE` events |
| Probe images and MicroVMs | Both current lists are empty |
| Probe artifact bucket | `HeadBucket` returns `404 Not Found` |
| Probe build and execution roles | Both `GetRole` calls return `NoSuchEntity` |
| Exact probe log group | Absent from the prefix listing |
| Separate `town-agent` stack | Still `UPDATE_COMPLETE` |
| Separate `town-agent` image | Still `UPDATED`, latest active version `4.0` |

The `404` and `NoSuchEntity` errors are the expected absence checks, not failed
cleanup. CloudFormation may retain the deleted stack's history. The original
probe resources need no further removal. Local source backups and acceptance
evidence remain preserved; the unrelated old `town-agent` bucket remains
outside this cleanup.

Authoritative post-cleanup responses and the completion audit are under
`tmp/issue-165/cleanup-2026-11-05/post-cleanup/`. The deletion time above comes
from the final stack event; the stack's `DeletionTime` field marks the earlier
start of deletion at 12:38:50.729 UTC.

## Inventory before cleanup

| Resource | Observed state | Cleanup owner |
| --- | --- | --- |
| CloudFormation `txing-agent-probe-165` | `UPDATE_COMPLETE`, termination protection off | Delete last, by the captured stack ARN |
| S3 `txing-agent-probe-165-artifacts-drlwioj2trjx` | Four `probe/*.zip` objects, **257,693 bytes** total; versioning never enabled, four null versions, no delete markers or multipart uploads | Delete the four reviewed objects; CloudFormation deletes the empty bucket |
| IAM `txing-agent-probe-165-BuildRole-5jxaosB1sqzQ` | One inline policy; no attached managed policy or instance profile; last used 2026-10-22 09:18:02 UTC | CloudFormation |
| IAM `txing-agent-probe-165-ExecutionRole-WK7zEUC0YQe9` | One inline policy; no attached managed policy or instance profile; last used 2026-10-22 14:04:51 UTC | CloudFormation |
| CloudWatch `/aws/lambda-microvms/txing-agent-probe-165` | Seven-day retention, **0 stored bytes / 0 current events**; 15 historical stream records; deletion protection off | CloudFormation |
| Probe MicroVMs | Zero entries in each of the four image-filtered current inventories; zero active probes in the regional inventory | No termination needed for the observed state |

Four separately created MicroVM images are **outside** the stack:

| Image name | Version | Version state / activation | Image state |
| --- | --- | --- | --- |
| `txing-agent-probe-165-fca66c894955` | `1.0` | `FAILED / INACTIVE` | `CREATE_FAILED` |
| `txing-agent-probe-165-f1eaabeaae78` | `1.0` | `FAILED / INACTIVE` | `CREATE_FAILED` |
| `txing-agent-probe-165-5db8fe4d0334` | `1.0` | `SUCCESSFUL / ACTIVE` | `CREATED` |
| `txing-agent-probe-165-c963a8c8a9df` | `1.0` | `SUCCESSFUL / ACTIVE` | `CREATED` |

Each version has two build records, for Graviton generations 3 and 4: eight
build records in total, not eight additional images. Delete the parent images
through the MicroVM API. There is no separate build-deletion command. AWS
documents whole-image and version deletion separately; its toolkit says to use
whole-image deletion for the last remaining version.
([API](https://docs.aws.amazon.com/lambda/latest/microvm-api/API_DeleteMicrovmImage.html),
[AWS toolkit](https://github.com/aws/agent-toolkit-for-aws/blob/main/skills/specialized-skills/serverless-skills/aws-lambda-microvms/references/getting-started.md))

The original deployed stack contained only the bucket, log group and two roles.
Its template had no `Retain` or `Snapshot` deletion policy. Deleting the stack alone
would leave the four external images, and its nonempty bucket would prevent
complete stack deletion. CloudFormation requires the S3 bucket to be empty.
([CloudFormation deletion policy](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-deletionpolicy.html),
[bucket deletion](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-s3-bucket.html))

Successful image versions retain storage even with no running MicroVMs. No
image-storage byte count or dollar estimate was established by this audit.
([AWS cost guidance](https://docs.aws.amazon.com/lambda/latest/dg/microvms-best-practices.html))

## Dependency checks and exclusions

The newer `town-agent` deployment is separate. Its current parameters select
image `town-agent`, version `4.0`, release `0.1.1`. All four of its image
versions use its own bucket, build role and log group, and use the AWS-managed
`al2023-1` base rather than a probe image. The deployed stack template and
controller configuration contain no probe reference. No regional Lambda
function uses either probe role. No CloudFormation exports exist in the
inspected region. No dependency on the probe was found in these checks.

Exclude from this cleanup:

- The `town-agent` stack, image and all its versions, artifact bucket, IAM
  roles/policy, controller, scheduler, IoT rule and logs.
- `town-agent-artifacts-pcvn5adegpvg`, left by a different deleted `town-agent`
  stack. This is a separate cleanup candidate, not an issue-165 resource.
- The TBot/rig IoT resources and existing MAVLink/video KVS channels. The probe
  execution role only received viewer/read permissions to those resources.
- AWS-managed base images, public network connectors and shared service-linked
  roles. This probe used managed public networking and created no customer
  VPC/NAT/network connector in its stack.
- Local acceptance evidence, source backups and repository files.

These are observed dependency checks, not proof against future configuration
changes or references in an uninspected account/Region. Refresh the initial
checks immediately before removal; do not launch or rebuild the retired probe
while cleanup is in progress.

## Preserved evidence

Raw AWS responses and the exact resource allowlist are under
`tmp/issue-165/cleanup-2026-11-05/`:

- `cleanup-plan.json`: observed ownership, resources, exclusions and order.
- `stack.json`, `stack-resources.json`, `stack-template.json`: deployed stack.
- `images.json`, `versions-*.json`, `builds-*-1.0.json`, `microvms-*.json`:
  image/build/runtime state.
- `bucket-*.json`, `source-backup-manifest.json` and `source-backup/probe/`:
  all four S3 source ZIPs downloaded and SHA-256 hashed before cleanup.
- `probe-log-details.json`, `probe-log-streams.json`, `probe-log-events.json`:
  retained log metadata and the current empty event result.
- `town-*`, `regional-functions.json`, `probe-*Role*.json` and `policy-*.json`:
  dependency and IAM inspection.
- `delete-objects-reviewed.json`: a prepared request containing exactly the
  four observed keys, with verbose per-object results. It was prepared for the
  operator's execution; no request was submitted by the assistant.

Source backups preserve the uploaded source packages, not AWS-managed image
snapshots. Rebuilding is required to recreate a deleted image. Old CloudWatch
events have already expired; metadata cannot restore them. Earlier captured
build/runtime logs and acceptance evidence remain under `tmp/issue-165/` and
are not removed. These local artifacts are not committed or a remote archive.

## Manual cleanup steps

The following stages record the manual procedure used for the completed
cleanup. They are reviewed operator commands, not an installed cleanup script.
For any future use, run stages separately from the same terminal and stop on
any failed check,
unexpected resource, active probe, `DELETE_FAILED`, S3 per-object error, or
changed versioning state. The assistant submitted no AWS mutation while
preparing or verifying this procedure.

### 1. Refresh identity, stack ownership and runtime state

```sh
cd /Users/Maxim/Developer/txing
cleanup165_dir=tmp/issue-165/cleanup-2026-11-05/manual-run
mkdir -p "$cleanup165_dir"

aws --profile mayor --region eu-central-1 --output json --no-cli-pager sts get-caller-identity \
  > "$cleanup165_dir/identity.json"
jq -e '.Account == "453102798330"' "$cleanup165_dir/identity.json"

aws --profile mayor --region eu-central-1 --output json --no-cli-pager cloudformation describe-stacks \
  --stack-name txing-agent-probe-165 > "$cleanup165_dir/stack.json"
cleanup165_stack_id=$(jq -er '.Stacks[0].StackId' "$cleanup165_dir/stack.json")
test "$cleanup165_stack_id" = \
  'arn:aws:cloudformation:eu-central-1:453102798330:stack/txing-agent-probe-165/846f71e0-cd2b-11f1-bf6a-02ffddb694ad'
cleanup165_bucket=$(jq -er '.Stacks[0].Outputs[] | select(.OutputKey=="ArtifactBucket") | .OutputValue' "$cleanup165_dir/stack.json")

aws --profile mayor --region eu-central-1 --output json --no-cli-pager cloudformation list-stack-resources \
  --stack-name "$cleanup165_stack_id" > "$cleanup165_dir/stack-resources.json"
cleanup165_build_role=$(jq -er '.StackResourceSummaries[] | select(.LogicalResourceId=="BuildRole") | .PhysicalResourceId' "$cleanup165_dir/stack-resources.json")
cleanup165_execution_role=$(jq -er '.StackResourceSummaries[] | select(.LogicalResourceId=="ExecutionRole") | .PhysicalResourceId' "$cleanup165_dir/stack-resources.json")
cleanup165_log_group=$(jq -er '.StackResourceSummaries[] | select(.LogicalResourceId=="Logs") | .PhysicalResourceId' "$cleanup165_dir/stack-resources.json")

aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms list-microvms \
  > "$cleanup165_dir/microvms.json"
jq -e '[.items[] | select(.imageArn | startswith("arn:aws:lambda:eu-central-1:453102798330:microvm-image:txing-agent-probe-165-")) | select(.state != "TERMINATED")] | length == 0' \
  "$cleanup165_dir/microvms.json"

aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms list-microvm-images \
  --query 'items[].{Name:name,State:state,ActiveVersion:latestActiveImageVersion}'
aws --profile mayor --region eu-central-1 --output json --no-cli-pager cloudformation describe-stacks \
  --stack-name town-agent --query 'Stacks[0].Parameters'
```

Confirm the four probe names above and the separate `town-agent` selection.
If new references or active probe VMs appear, resolve them before continuing.
The recorded state needs no terminate command.

### 2. Delete the four external probe images

Delete whole images, each with its single `1.0` version. Keep the bucket, roles
and logs until these deletions are terminal.

```sh
aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms delete-microvm-image \
  --image-identifier arn:aws:lambda:eu-central-1:453102798330:microvm-image:txing-agent-probe-165-fca66c894955 \
  > "$cleanup165_dir/delete-image-fca66c894955.json"

aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms delete-microvm-image \
  --image-identifier arn:aws:lambda:eu-central-1:453102798330:microvm-image:txing-agent-probe-165-f1eaabeaae78 \
  > "$cleanup165_dir/delete-image-f1eaabeaae78.json"

aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms delete-microvm-image \
  --image-identifier arn:aws:lambda:eu-central-1:453102798330:microvm-image:txing-agent-probe-165-5db8fe4d0334 \
  > "$cleanup165_dir/delete-image-5db8fe4d0334.json"

aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms delete-microvm-image \
  --image-identifier arn:aws:lambda:eu-central-1:453102798330:microvm-image:txing-agent-probe-165-c963a8c8a9df \
  > "$cleanup165_dir/delete-image-c963a8c8a9df.json"
```

Repeat this read-only check until all four are absent or `DELETED`.
`DELETING` is not completion; `DELETE_FAILED` requires inspection.

```sh
aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms list-microvm-images \
  --query 'items[?starts_with(name, `txing-agent-probe-165-`)].{Name:name,State:state}'
```

### 3. Remove only the four preserved S3 objects

Verify the backups and review the exact keys. Refresh versioning and contents;
the reviewed request applies to the observed unversioned bucket. If versioning
is now Enabled/Suspended, delete markers exist, or objects differ from the
manifest, stop and prepare a revised request rather than using recursive/forced
bucket deletion.

```sh
cat tmp/issue-165/cleanup-2026-11-05/source-backup-manifest.json
shasum -a 256 tmp/issue-165/cleanup-2026-11-05/source-backup/probe/*.zip
cat tmp/issue-165/cleanup-2026-11-05/delete-objects-reviewed.json

aws --profile mayor --region eu-central-1 --output json --no-cli-pager s3api get-bucket-versioning \
  --bucket "$cleanup165_bucket" --expected-bucket-owner 453102798330
aws --profile mayor --region eu-central-1 --output json --no-cli-pager s3api list-object-versions \
  --bucket "$cleanup165_bucket" --expected-bucket-owner 453102798330
aws --profile mayor --region eu-central-1 --output json --no-cli-pager s3api list-objects-v2 \
  --bucket "$cleanup165_bucket" --expected-bucket-owner 453102798330
```

After review, this one request names only the four observed objects:

```sh
aws --profile mayor --region eu-central-1 --output json --no-cli-pager s3api delete-objects \
  --bucket "$cleanup165_bucket" --expected-bucket-owner 453102798330 \
  --delete file://tmp/issue-165/cleanup-2026-11-05/delete-objects-reviewed.json \
  > "$cleanup165_dir/delete-objects-result.json"
jq -e '(.Errors // [] | length) == 0 and (.Deleted | length) == 4' \
  "$cleanup165_dir/delete-objects-result.json"

aws --profile mayor --region eu-central-1 --output json --no-cli-pager s3api list-objects-v2 \
  --bucket "$cleanup165_bucket" --expected-bucket-owner 453102798330 \
  > "$cleanup165_dir/bucket-after.json"
jq -e '(.Contents // [] | length) == 0' "$cleanup165_dir/bucket-after.json"
aws --profile mayor --region eu-central-1 --output json --no-cli-pager s3api list-object-versions \
  --bucket "$cleanup165_bucket" --expected-bucket-owner 453102798330
aws --profile mayor --region eu-central-1 --output json --no-cli-pager s3api list-multipart-uploads \
  --bucket "$cleanup165_bucket" --expected-bucket-owner 453102798330
```

Require no remaining versions, delete markers or multipart uploads before
stack deletion. A successful HTTP response from multi-object deletion can still
contain per-object errors, which is why its `Errors` field is checked.

### 4. Delete the stack and its four owned resources

```sh
aws --profile mayor --region eu-central-1 --output json --no-cli-pager cloudformation delete-stack \
  --stack-name "$cleanup165_stack_id"
aws --profile mayor --region eu-central-1 --output json --no-cli-pager cloudformation wait stack-delete-complete \
  --stack-name "$cleanup165_stack_id"
```

CloudFormation removes the empty bucket, both roles and their inline policies,
and the log group. Do not remove those stack resources separately first. If
deletion fails, inspect the event reason rather than using force deletion or
retaining resources that this cleanup intends to remove:

```sh
aws --profile mayor --region eu-central-1 --output json --no-cli-pager cloudformation describe-stack-events \
  --stack-name "$cleanup165_stack_id" \
  > "$cleanup165_dir/stack-delete-events.json"
```

### 5. Verify removal and the separate deployment

```sh
aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms list-microvm-images \
  --query 'items[?starts_with(name, `txing-agent-probe-165-`)].{Name:name,State:state}'
aws --profile mayor --region eu-central-1 --output json --no-cli-pager s3api head-bucket \
  --bucket "$cleanup165_bucket" --expected-bucket-owner 453102798330
aws --profile mayor --region eu-central-1 --output json --no-cli-pager iam get-role \
  --role-name "$cleanup165_build_role"
aws --profile mayor --region eu-central-1 --output json --no-cli-pager iam get-role \
  --role-name "$cleanup165_execution_role"
aws --profile mayor --region eu-central-1 --output json --no-cli-pager logs describe-log-groups \
  --log-group-name-prefix "$cleanup165_log_group"

aws --profile mayor --region eu-central-1 --output json --no-cli-pager cloudformation describe-stacks \
  --stack-name town-agent --query 'Stacks[0].StackStatus'
aws --profile mayor --region eu-central-1 --output json --no-cli-pager lambda-microvms get-microvm-image \
  --image-identifier arn:aws:lambda:eu-central-1:453102798330:microvm-image:town-agent
```

Expected results: probe images absent/`DELETED`, bucket `404`, both roles
`NoSuchEntity`, exact probe log group absent, and the `town-agent` stack/image
still present. A `403` is not proof of deletion. CloudFormation `DELETE_COMPLETE`
history and service tombstones can remain visible after resources are removed.
Record the execution time and resulting AWS responses; preparation is not
cleanup-completion evidence.
