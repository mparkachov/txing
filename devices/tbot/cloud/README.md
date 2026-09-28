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
