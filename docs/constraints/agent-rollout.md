# Initial agent replacement and manual retirement

Status: operator runbook for the planned C++ replacement. Repository cleanup
does not imply deployed AWS cleanup. No replacement runtime, controller,
deployment, or publication command is available at the #163 baseline.

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
5. After all old writers are stopped, archive the optional `agent` shadow for
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
for this cleanup. Office still reads raw optional JSON and needs no runtime
change here. No firmware flash or device binary update is required by #163.

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
