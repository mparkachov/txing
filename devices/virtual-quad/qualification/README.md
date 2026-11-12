# Lambda MicroVM qualification for virtual quadcopter

Use this runbook for [issue #176](https://github.com/mparkachov/txing/issues/176).
It runs stock ArduCopter Copter-4.7.2 SITL (the exact commit is in the
[Dockerfile](Dockerfile)), a 640 × 360, 15 fps H.264 moving test pattern, and
independent txing KVS masters for video and real MAVLink 2 telemetry. SITL
starts disarmed with fresh scratch. The probe forwards one original MAVLink 2
frame per ordered, reliable data-channel message. The probe has no uplink to
SITL. The test pattern measures the encoder and transport workload; the later
media and flight issues measure the pose-driven renderer and actual flight.

## Local smoke test

From the repository root, using the existing Lima/containerd engine:

```sh
just virtual-quad::qualification-build
nerdctl.lima image inspect txing-virtual-quad-qualification:local
nerdctl.lima run --rm --platform linux/arm64 --network none \
  txing-virtual-quad-qualification:local local
```

The build and smoke test run natively on an ARM64 Lima guest.

The build verifies loader closure and that GStreamer finds the four required
plugins. Record the image size and the build's `ldd` output. The image contains
the ArduPilot and submodule revisions, KVS SDK commit and Debian package
versions at `/opt/quad/evidence/`. Check for `QUAD_READY mode=local` followed by
at least two `QUAD_MEDIA_SAMPLE` lines with increasing SITL boot time and
approximately 15 encoded fps and 800 encoded kbit/s. Stop the container and look for
`QUAD_CHILDREN_REAPED`. The local image is a test fixture for the simulator
and media workload.

## MicroVM qualification

Issue #176 uses a disposable Linux ARM64 Lambda MicroVM in
`eu-central-1`. Build the bundle from the repository root in the same shell
you'll use to publish it.

```sh
bundle=$(just virtual-quad::microvm-package) && printf '%s\n' "$bundle"
```

The recipe prints build output and the SHA-256 to stderr and returns the
archive path to `bundle`. It validates the same
Dockerfile and prebuilt ARM64 payload that the snapshot builder receives.
Use the local image with the `microvm-local` argument to exercise the hooks
without AWS credentials or network access. The default `microvm` argument
uses the execution role and both qualification KVS channels.
[Architecture plan](../../../docs/virtual-quadcopter-architecture.md)

### Prepare the test image

Run these operator steps in the configured Frankfurt test account. The
stack owns the artifact bucket, scoped IAM roles, and log group. Create
each missing channel once. A failed CLI command should be resolved before
running its dependent step.

```sh
quad_aws() { aws --region eu-central-1 --no-cli-pager "$@"; }
stack=quad-qualification-microvm-176
quad_aws cloudformation deploy --stack-name "$stack" --capabilities CAPABILITY_IAM \
  --template-file devices/virtual-quad/qualification/microvm.template.yaml
quad_aws kinesisvideo create-signaling-channel \
  --channel-name quad-qualification-176-board-video --channel-type SINGLE_MASTER
quad_aws kinesisvideo create-signaling-channel \
  --channel-name quad-qualification-176-mavlink --channel-type SINGLE_MASTER
```

If you already built a bundle, set `bundle` to its ZIP path in this shell.
Record the bundle checksum, managed base version and returned image version
when you publish.

```sh
quad_image_inputs() {
  if [ ! -f "${bundle:-}" ]; then
    printf '%s\n' 'Set bundle to an existing ZIP or run bundle=$(just virtual-quad::microvm-package).' >&2
    return 1
  fi
  outputs=$(quad_aws cloudformation describe-stacks --stack-name "$stack" \
    --query 'Stacks[0].Outputs' --output json) || return 1
  bucket=$(printf '%s\n' "$outputs" | jq -er '.[] | select(.OutputKey == "ArtifactBucket").OutputValue') || return 1
  build_role=$(printf '%s\n' "$outputs" | jq -er '.[] | select(.OutputKey == "BuildRoleArn").OutputValue') || return 1
  execution_role=$(printf '%s\n' "$outputs" | jq -er '.[] | select(.OutputKey == "ExecutionRoleArn").OutputValue') || return 1
  logs=$(printf '%s\n' "$outputs" | jq -er '.[] | select(.OutputKey == "LogGroup").OutputValue') || return 1
  base=arn:aws:lambda:eu-central-1:aws:microvm-image:al2023-1
  base_catalog=$(quad_aws lambda-microvms list-managed-microvm-image-versions \
    --image-identifier "$base" --output json) || return 1
  base_version=$(printf '%s\n' "$base_catalog" | jq -er '
    [.items[] | select(.status == "AVAILABLE" and
      any(.supportedCpuConfigurations[]; .architecture == "ARM_64"))]
    | map(.imageVersion | split(".")[0] | tonumber) | max // error("No available ARM64 base version")') || return 1
  checksum_line=$(shasum -a 256 "$bundle") || return 1
  bundle_sha=${checksum_line%% *}
  key="qualification/$bundle_sha/bundle.zip"
  connector=arn:aws:lambda:eu-central-1:aws:network-connector:aws-network-connector
  printf 'Managed base version %s, artifact s3://%s/%s\n' "$base_version" "$bucket" "$key"
}
```

Use `quad_publish_image create` for the first version and
`quad_publish_image update` to build a replacement version of the existing
image. The update looks up the qualification image ARN in the configured
account. Inspect the returned version before submitting another build.

```sh
quad_publish_image() {
  case "${1:-}" in
    create) set -- create-microvm-image --name "$stack" ;;
    update)
      image_catalog=$(quad_aws lambda-microvms list-microvm-images --output json) || return 1
      target_arn=$(printf '%s\n' "$image_catalog" | jq -er --arg name "$stack" '
        [.items[] | select(.name == $name) | .imageArn]
        | if length == 1 then .[0] else error("Expected one qualification image named \($name)") end') || return 1
      set -- update-microvm-image --image-identifier "$target_arn"
      ;;
    *) printf '%s\n' 'Use quad_publish_image create or quad_publish_image update.' >&2; return 1 ;;
  esac
  quad_image_inputs || return 1
  if ! quad_aws s3api put-object --bucket "$bucket" --key "$key" --body "$bundle" \
    --if-none-match '*' --checksum-algorithm SHA256; then
    uploaded_sha=$(quad_aws s3api head-object --bucket "$bucket" --key "$key" \
      --checksum-mode ENABLED --query ChecksumSHA256 --output text) || return 1
    local_sha=$(openssl dgst -sha256 -binary "$bundle" | openssl base64 -A) || return 1
    if [ -z "$local_sha" ] || [ "$uploaded_sha" != "$local_sha" ]; then
      printf 'Could not verify the SHA-256 of s3://%s/%s\n' "$bucket" "$key" >&2
      return 1
    fi
  fi
  image_result=$(quad_aws lambda-microvms "$@" \
    --base-image-arn "$base" --base-image-version "$base_version" \
    --code-artifact "uri=s3://$bucket/$key" --build-role-arn "$build_role" \
    --cpu-configurations architecture=ARM_64 --resources minimumMemoryInMiB=4096 \
    --egress-network-connectors "$connector:INTERNET_EGRESS" \
    --logging "cloudWatch={logGroup=$logs}" \
    --hooks file://devices/virtual-quad/qualification/microvm-hooks.json \
    --client-token "$bundle_sha" --output json) || return 1
  image_arn=$(printf '%s\n' "$image_result" | jq -er .imageArn) || return 1
  image_version=$(printf '%s\n' "$image_result" | jq -er .imageVersion) || return 1
  printf '%s version %s\n' "$image_arn" "$image_version"
}
```

Run the appropriate publish command, then wait for the returned image
version to report `ACTIVE`.

```sh
quad_aws lambda-microvms get-microvm-image-version \
  --image-identifier "$image_arn" --image-version "$image_version"
```

### Launch and measure

Launch one VM at a time. The launch helper records the start time and
retains the request token on failure. Use the same token and inputs to
replay an ambiguous result. For a new cold start, wait for the previous VM to
reach `TERMINATED`, run `unset quad_run_token`, then run `quad_launch kvs 840`.
Follow the dedicated log group while Lambda creates its log stream. Match the
`QUAD_MICROVM_RUN` log entry to the returned VM ID.

```sh
quad_launch() {
  if [ -z "${quad_run_token:-}" ]; then
    quad_run_token=$(uuidgen) || return 1
    date -u +%Y-%m-%dT%H:%M:%SZ
  fi
  vm_id=$(quad_aws lambda-microvms run-microvm \
    --image-identifier "$image_arn" --image-version "$image_version" \
    --execution-role-arn "$execution_role" --client-token "$quad_run_token" \
    --maximum-duration-in-seconds "$2" \
    --ingress-network-connectors "$connector:NO_INGRESS" \
    --egress-network-connectors "$connector:INTERNET_EGRESS" \
    --logging "cloudWatch={logGroup=$logs}" \
    --run-hook-payload "{\"mode\":\"$1\"}" --query microvmId --output text) || return 1
  printf '%s\n' "$vm_id"
}
```

```sh
quad_launch kvs 840 &&
quad_aws lambda-microvms get-microvm --microvm-identifier "$vm_id" &&
quad_aws logs tail "$logs" --since 20m --follow
```

Stop log following with Ctrl+C. To stop the VM, record the request time and
poll until `GetMicrovm` reports `TERMINATED`.

```sh
date -u +%Y-%m-%dT%H:%M:%SZ
quad_aws lambda-microvms terminate-microvm --microvm-identifier "$vm_id"
quad_aws lambda-microvms get-microvm --microvm-identifier "$vm_id"
```

Use `quad_launch hang-on-stop 840` for the unresponsive supervisor test
and `quad_launch kvs 120` for the platform deadline test. Use a fresh
token for each new VM. Scope the final inventory to this simulator image.

```sh
quad_aws lambda-microvms list-microvms --image-identifier "$image_arn"
```

1. Build a dedicated simulator bundle using the agent's ARM64 packaging as a
   reference. Record the native dependency closure, bundle size and checksums,
   managed base and simulator image version. Capture an idle snapshot and
   initialize the test session through the run hook. Use a dedicated
   execution role, CloudWatch logs, managed Internet egress, and
   `NO_INGRESS`. The two disposable KVS channels
   `quad-qualification-176-board-video` and `quad-qualification-176-mavlink`
   can be reused. [Agent release packaging](../../../docs/components/agent.md#immutable-releases)
2. Launch three fresh VMs from the same pinned version, one at a time.
   Record each launch request time, VM state, application ready timestamp,
   CPU, memory and scratch growth. Verify readiness within 90 seconds of
   launch and confirm both KVS streams from the browser. Use `GetMicrovm` to
   record VM state separately from application readiness.
3. Start the test-configured Office dev server from `office/` with
   `bun run dev`. Sign in through the test Cognito pool and open
   `/virtual-quad-qualification.html` in the same tab. Enter the two channel
   names. Test automatic ICE first. On a separate run select **Force TURN**,
   confirm that the selected local candidate is `relay` on both streams,
   and sustain 12 minutes of media. Rejoin with a second browser after minute
   five and again after minute ten. Keep the first browser in the foreground.
   Download both browser JSON exports. In 95% of five-second windows, target
   at least 12 decoded fps at 640 × 360. Check that MAVLink frames and
   heartbeats advance without invalid messages and that the SITL clock
   advances at 0.95–1.05× wall time in 30-second windows.
4. Terminate a healthy VM with `TerminateMicrovm` and record the cleanup
   markers and `TERMINATED` state. Repeat with a deliberately unresponsive
   supervisor or terminate hook, with the platform deadline far enough away
   to distinguish API termination from expiry. Record request time,
   `terminatedAt`, state reason and peer closure. Use a separate run to
   verify the platform maximum duration. Check the dedicated simulator
   inventory for any remaining VMs. [MicroVM termination](https://docs.aws.amazon.com/lambda/latest/dg/microvms-launching.html)
5. Record the measurements and discrepancies in issue #176 before starting
   lifecycle integration. Keep raw logs in approved private storage.

### Retire the MicroVM qualification resources

Confirm all VMs for this image are terminal. Preserve the qualification
evidence, then delete the dedicated image and wait for deletion before
removing its bundle from S3. Delete the MicroVM qualification stack after
its artifact bucket is empty. Delete the two qualification KVS channels
if the test no longer needs them.

## Retire the Fargate qualification resources

Use the same AWS profile and region as the original setup. A read-only check
on November 11, 2026 found an empty ECR repository named
`quad-qualification-176` and two active qualification signaling channels in
`eu-central-1`. CloudFormation reported the qualification stack absent, and
no subnet carried the qualification tag. A follow-up check after operator
cleanup confirmed that the repository and both channels were gone.

- If the stack exists in the environment you are cleaning, use its `Cluster`
  output to list and stop any qualification ECS tasks. Wait for the tasks to
  stop, preserve any logs you need, then delete the `quad-qualification-176`
  stack and wait for deletion. The stack owns the ECS resources, IAM roles,
  security group and log group. The existing subnet and VPC remain shared
  network resources. Remove only the `txing:qualification=virtual-quad-176`
  tag if you added it for this test.
- To remove the empty qualification repository, run the following in the
  original account and region. This command requires an empty repository.
  If you pushed an image since the check, preserve any required evidence and
  remove only the qualification images before deleting the repository.

```sh
aws ecr delete-repository --region eu-central-1 --repository-name quad-qualification-176
```

- Keep the two qualification signaling channels if you plan to reuse them
  for the MicroVM test. For a full teardown, resolve the exact ARNs and delete
  the channels. Preserve channels belonging to registered devices.

```sh
for channel in quad-qualification-176-board-video quad-qualification-176-mavlink; do
  if channel_arn=$(aws kinesisvideo describe-signaling-channel --region eu-central-1 \
    --channel-name "$channel" --query 'ChannelInfo.ChannelARN' --output text) &&
    [ -n "$channel_arn" ] && [ "$channel_arn" != None ]; then
    aws kinesisvideo delete-signaling-channel --region eu-central-1 --channel-arn "$channel_arn"
  fi
done
```
