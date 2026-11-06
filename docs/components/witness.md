# Witness

Witness is the Go Sparkplug projection Lambda deployed by the standalone
`witness/` stack.

## Responsibilities

- subscribe to Sparkplug MQTT through an IoT topic rule
- project Sparkplug topic identity and payload metrics into the `sparkplug` named shadow
- keep the AWS-side lifecycle read model separate from the live Sparkplug publisher
- provide independent [agent shutdown repair](#agent-shutdown-watch)

Witness is the only authority that writes the `sparkplug` named shadow for
rig and unit Things.

## Agent shutdown watch

The existing Go witness Lambda provides stop-only repair. The C++ controller
handles prompt shutdown. Configure both stacks with the same dedicated
Frankfurt MicroVM image name.

### Ownership and timing

- The C++ controller remains the only operational writer of the `agent` shadow.
  Witness reads it, describes MicroVMs and requests termination. It cannot launch
  an agent, grant an assignment, extend an activation, or reset an expired budget.
- Witness still projects only Sparkplug MQTT into the `sparkplug` shadow. A
  bounded watch check follows successful projection, including unchanged metrics.
  Watch failure does not turn a successful projection into a failed invocation.
- MQTT traffic is not periodic or guaranteed. A separate one-minute EventBridge
  Scheduler schedule invokes the same witness Lambda even when devices and the
  controller are silent. Its state does not follow the controller's automation
  switch.
- For an off assignment (`stopping`, `stopped`, `expired`, `error`), wait 120
  seconds from `controller.stopRequestedAt`. The controller records that value
  on the first stopping write and retains it through repeated writes. Clear it
  when the run is removed or a non-stopping run is written. Older off records
  without the field use the lifecycle-state metadata timestamp; absent or future
  timestamps do not authorize immediate termination.
- An expired activation becomes eligible 120 seconds after its persisted
  deadline even if a failed controller leaves the shadow showing `running`.
  Session/control shutdown still occurs at the deadline. The grace period
  applies to compute repair, not to device authority or a new activation budget.
- In healthy AWS operation, the minute schedule normally requests termination
  between two and three minutes after the off time or deadline. Scheduling,
  invocation and service latency can extend the interval. Confirm terminal
  state in a later inventory.

### Scope and failure handling

Configure witness with the same dedicated Frankfurt image name as the agent
stack. Inventory covers every version of that image. Get and terminate IAM
permissions are scoped to its image ARN; the watch has no run, resume, token,
or pass-role permissions and receives no agent-shadow-write interface.
The existing witness role grants shadow access on `thing/*` for Sparkplug
projection. That wildcard matches both classic and named-shadow resources.
A named shadow uses `thing/THING/SHADOW`, such as `thing/THING/sparkplug` or
`thing/THING/agent`; the bare Thing ARN does not match those named resources.
Controller-only agent writes remain an application ownership rule under the
current wildcard policy. See the [AWS IoT action-resource reference](https://docs.aws.amazon.com/iot/latest/developerguide/iot-action-resources.html).

Retain healthy starting and running assignments, including runs with individual
media errors. Check the current VM/image identity and re-read its assignment
before terminating an off run. A replacement assignment or recovered lifecycle
cancels a stale decision. Process inventory pages before requesting later pages,
deduplicate actionable identities and bound/reject cyclic pagination. Per-item
failures leave other known off runs eligible for cleanup.

An unassigned instance of this dedicated image is eligible 120 seconds after
its AWS start time. This covers ambiguous launches whose IDs were never saved.
Before terminating it, successfully enumerate registered Things and read their
agent shadows, including Things whose agent capability has since been removed, then repeat the assignment inventory. A missing
shadow is distinct from an unreadable or malformed shadow. Incomplete reads and
conflicting identity claims cannot prove an orphan and defer that decision.
An unresolved controller reservation is retained for its activation. The
controller can supersede a fenced reservation without a known VM ID only after
a later directly observed, currently authorized activation. It conditionally
persists the new run before launch; old instances remain unassigned and eligible
for this watch. Neither assignment retirement nor a termination request proves
the old VM is off. Known VM IDs still require terminal confirmation.

The watch is bounded to 25 seconds per scheduled invocation and four seconds
after projection. Subsequent minute passes retry incomplete work. Service/read
failures return errors on the scheduled path and appear in witness logs and
Lambda error metrics. Ordinary grace/terminal-state waiting reports incomplete
without adding asynchronous retry traffic. Projection-path failures are logged
and deferred to the schedule. Do not log tokens, credentials, launch payloads,
or complete shadows.

The watch shares AWS service dependencies with the controller. A shared
outage can delay termination until recovery or the platform lifetime limit.

Assigned-run shutdown requires an off agent
shadow or its expired deadline. If the controller fails before
recording an early device shutdown and leaves a non-expired `running`
assignment, witness preserves it until the shadow becomes off or the deadline
expires. Sparkplug inactivity alone does not authorize watch termination.

## Deploy

Create or update the witness Lambda stack:

```bash
just witness::deploy
```

To configure the independent watch, run the deployment manually with the
existing environment and dedicated image name:

```sh
just witness::deploy <environment-stack> <agent-image-name>
```

The first deployment defaults the image to `disabled`; later deployments that
omit it preserve the existing CloudFormation parameter. Publish a new shared
`lambda` release for witness source changes before enabling its schedule. The
controller release must persist `stopRequestedAt` for off-time grace.

Publish release-built runtime Lambda code after the GitHub release exists:

```bash
just release::publish lambda
```

`witness::deploy` creates the shared Lambda artifact bucket when needed and
seeds a placeholder `lambda/txing-witness-lambda/current/bootstrap.zip` object
before creating the function. CloudFormation uses this placeholder for bootstrap. Production code comes
from GitHub release assets.
`release::publish lambda` publishes already-built artifacts to all three
existing Go runtime Lambda functions together.

The deeper projection semantics are documented in:

- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
- [Unit thing shadow model](../../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../../devices/unit/docs/device-rig-shadow-spec.md)

## Verify shutdown repair

For an operator-run regression test, keep both agent launch gates disabled.
Pause the controller repair schedule and set its reserved concurrency to zero.
Wait longer than its 120-second timeout to drain in-flight work. Leave the
independent witness schedule enabled.

Use one fixture VM at a time with an independent hosting cap long enough to
observe witness termination. An unassigned VM has no stored assignment. To
test assigned shutdown, use a separate untyped test Thing with no credentials,
rig or signaling channels. Observe a healthy synthetic assignment past the
orphan grace, then set its first `stopRequestedAt` without changing the run
identity. Test deadline expiry separately while its record still says
`running`. Keep fixture assignments off real device Things.

Record preservation through each grace period, the witness request and the
subsequent terminal AWS state before the hosting cap. If the watch fails,
terminate the fixture VM manually. After confirming terminal inventory, remove
only the fixture records and restore controller concurrency to one and its
repair schedule. [Released watch acceptance](https://github.com/mparkachov/txing/issues/170)
