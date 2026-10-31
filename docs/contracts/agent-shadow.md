# Cloud agent shadow

Status: replacement contract established by
[Issue #163](https://github.com/mparkachov/txing/issues/163). The C++ runtime and
controller are implemented under [milestone 10](https://github.com/mparkachov/txing/milestone/10);
bounded source-build evidence is recorded in the
[cloud acceptance history](../agent-cloud-build-validation.md).
This contract replaces the old ECS task/public UDP status directly.

The `agent` capability owns the `agent` named shadow for cloud operational
diagnostics. Device types opt in through their manifest capability list; TBot
is the current supported type. Provisioning and discharge use the same declared
capability-to-shadow mapping as other capabilities. Its
[schema](../../devices/tbot/aws/agent-shadow.schema.json),
[stopped default](../../devices/tbot/aws/default-agent-shadow.json), and
[running example](../../devices/tbot/aws/fixtures/agent-shadow.json) are
authoritative field definitions. It has no desired state or command interface.

## Ownership and interpretation

The C++ controller is the sole operational writer. Provisioning may create a
missing stopped default; re-enlistment preserves existing payloads. Manual
initial replacement is described in the [rollout runbook](../constraints/agent-rollout.md).
Cloud runtimes expose status for controller sampling and verify current
assignment/lifecycle themselves; they do not update the shadow or invoke an old
readiness controller. Local runs log locally and never write this shadow.
Runtime IAM must grant no `agent` shadow write permission.

| Reported field | Meaning |
| --- | --- |
| `run.id` | Opaque controller-persisted launch identity, allocated before launch and reused for ambiguous-launch retries |
| `run.microvmId` | Hosting service identity, present once known; not a device identity or authentication credential |
| `run.release` | Exact immutable agent release version in `MAJOR.MINOR.PATCH` form; replacements do not silently change existing runs |
| `activation.id`, `startedAt`, `deadline` | Persistent device activation and its absolute cloud execution limit; shared by all replacement runs |
| `lifecycle.state` | `stopped`, `starting`, `running`, `stopping`, `expired`, or `error`; describes cloud execution rather than WebRTC readiness |
| `lifecycle.verifiedAt` | Time the controller last verified authoritative device lifecycle and current assignment; required when starting/running |
| `endpoint` | Authenticated HTTPS base URL for the current running MicroVM; no raw UDP/IP fields, credentials, or attachment token |
| `runtime.runId`, `sampledAt` | Identity and receipt time of the controller's fresh runtime sample |
| `runtime.mavlink.state`, `lastError` | Independent MAVLink connection state and actionable operation/error detail |
| `runtime.video.state`, `framesReceived`, `lastFrameAt`, `lastError` | Independent video state, cumulative encoded frames delivered to the operator in this run, last frame receipt time, and its error |
| `runtime.control.state`, `lastError` | `observing`, `acquiring`, `held`, or `lost`; sampled session authority, not a grant to the reader |
| `lastError` | Controller/launch/lifecycle error; does not replace individual connection/control errors |
| `controller` | Durable reconciliation state: last verified projection version, source timestamp and activity, last inactive observation time, the start of any controller verification outage, and the current run's activation, phase, and exact non-secret launch request |
| `controller.stopRequestedAt` | First stopping-write time for the current run; repeated writes retain it so witness's two-minute repair grace cannot be postponed |

All times are integer Unix epoch seconds in UTC. `sampledAt` is the controller's
sample receipt time; it must not be refreshed by replaying a cached response.
`lastFrameAt` is wall-clock receipt time for diagnostics, not the presentation
timestamp delivered by the operator interface. Counters reset with `run.id`.
Errors retain useful operation context without credentials, tokens, or signed
URLs. A healthy MAVLink connection must not erase a video error, or vice versa.
The launch request may contain only operational configuration and identities;
it must never contain credentials, an attachment token, or another secret.
The MicroVM launch `clientToken` is an idempotency identity, not an
authentication token; it is the same non-secret opaque ID stored as `run.id`.

Nullable fields may be absent: AWS IoT applies null updates as property deletion.
The default includes explicit nulls for initialization; its stored response may
contain only `lifecycle.state=stopped`. Consumers treat missing nullable fields
as null, not as retained values. Service `metadata`, `version`, `timestamp`, and
`clientToken` may accompany the payload. Partial update requests are not full
schema documents.

## Lifecycle, authorization, and fencing

`starting` reserves run/release identity and an activation before a launch.
`running` means the controller verified cloud execution and its assignment;
connections can independently be disconnected, connecting, connected, or in
error. An endpoint is allowed only for a running run with a known MicroVM ID.
Temporary media/telemetry loss belongs to session recovery, not process
replacement. The fixture deliberately shows video failure with MAVLink intact.

`stopping`, `stopped`, `expired`, and `error` expose no usable endpoint. A final
run/sample may remain for diagnosis, explicitly tied to its original identity
and timestamp; it cannot establish present control or connectivity. Expiry
retains the activation record and deadline so a repair pass cannot restart the
same activation. Total cloud execution is at most fifty minutes from activation
at the current project stage (the [2026-10-23 duration decision](../constraints/agent-session-limit.md)),
including retries, replacements, and publication. Only a subsequent verified
inactive-to-active transition permits a fresh activation budget.

A fenced launch with no known MicroVM ID remains reserved for its activation.
A later directly observed and unexpired activation may supersede that unknown
reservation with a conditionally persisted new run. The old request is never
retried; late results cannot alter the replacement, and leftover instances are
handled as orphans by the controller/watch. This is assignment revocation, not
proof that compute is off. Runs with a known MicroVM ID retain that identity
until terminal state is confirmed.

The controller must directly observe verified inactive and then active states
to recognize a later transition. If the inactive interval is missed, it retains
the expired activation and fails closed until another such transition is
observed. An incomplete or unreadable projection is not evidence of inactivity.
This limitation was accepted by the operator on 2026-10-28; witness does not
retain an activation history for the repair pass to reconstruct.
An initially active projection without an earlier inactive observation also
fails closed. The controller rejects missing, repeated or older Sparkplug
source timestamps as transition evidence, including old last-will timestamps;
the shadow's own version alone cannot rule out a replayed source message. The
budget begins at the last verified inactive observation, a conservative lower
bound on the transition time. Long controller outages or clock irregularities
can therefore shorten the remaining budget or require another transition.

The controller must compare the current run and activation before every write,
use version-conditional shadow updates, and resample after conflicts. Samples
must match `runtime.runId == run.id` and the currently assigned MicroVM. Changing
run identity clears the old endpoint and sample before publishing the new run.
Late responses from superseded runs cannot restore either. Orphan termination
and launch reconciliation remain controller responsibilities.

The independent [witness shutdown watch](../constraints/agent-watch.md) is an
operator-approved stop-only repair path. It reads this shadow and requests
MicroVM termination after a grace period; it never writes agent status or
creates activations. It also checks persisted deadlines when the controller
has stopped updating lifecycle state. For assigned runs, the operator limited
watch shutdown evidence to an off agent shadow or an expired deadline;
Sparkplug inactivity alone does not authorize watch termination.

The JSON Schema checks structure and lifecycle/endpoint constraints. Dynamic
identity equality, monotonic deadlines, elapsed time, freshness, and conditional
write authorization are enforced and tested by the controller/runtime. A valid
JSON document alone proves none of them.

Readers retain both identity and freshness. Shadow `timestamp` is not evidence
that every nested status was sampled then. Attachment discovery must verify
current assignment, active device lifecycle, unexpired deadline, and live
authenticated endpoint rather than trusting a stored URL or sample alone.
The runtime polls authority every two seconds and stops after fifteen seconds
without verification. Stale assignment or shutdown releases control and denies
usable attachment. Attachment uses short-lived, port-scoped AWS authentication,
one manual attachment, and the existing cloud session/lease.
The controller stores `controller.unverifiedSince` when its own verification
first fails. On a later pass after fifteen seconds of continuous failure, it
fences the run unless authenticated status for that exact running assignment
proves that the runtime has verified its authority within fifteen seconds,
including the time spent fetching status. This evidence can only defer a stop;
it cannot authorize a launch or endpoint or extend the activation. A successful
controller verification clears the timer. It is independent of the last
controller sweep, optional in older records, and never represents an inactive
edge. A clock reversal across a persisted failure interval fences the run.

## Device and Office boundaries

Rig/witness remain device lifecycle authorities. The registry declares `agent`
for supported device types, and the rig publishes `capability.agent` availability
when the device is born at REDCON 1 or 2. This authorizes cloud agent execution;
the `agent` shadow records actual cloud execution and errors. Agent readiness
does not gate device REDCON, avoiding a dependency cycle at startup. Missing or
invalid availability is unverified; explicit false revokes execution. Registry
capability removal also revokes execution.
Office discovers and reads this shadow from declared capabilities, independently
of the device type name, and isolates missing/read-error states. It does not use this diagnostic
sample to grant control, determine REDCON, or block normal device operation.

Observation remains the operator default. Explicit control acquires a free
board lease with `takeover=false` and permits full MAVLink, including pre-arm
traffic. The session retains control across arm/disarm/re-arm; client inactivity,
disconnect, WebRTC/lease loss, lifecycle shutdown, or process shutdown releases
it, without automatic reacquisition. See the
[agent design](../components/agent.md) and [board protocol](board-mavlink.md).
