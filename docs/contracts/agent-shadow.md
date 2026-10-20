# Cloud agent shadow

Status: replacement contract established by
[Issue #163](https://github.com/mparkachov/txing/issues/163). The C++ runtime and
controller are still planned under [milestone 10](https://github.com/mparkachov/txing/milestone/10).
This contract replaces the old ECS task/public UDP status directly.

The optional TBot `agent` named shadow is cloud operational diagnostics. Its
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

All times are integer Unix epoch seconds in UTC. `sampledAt` is the controller's
sample receipt time; it must not be refreshed by replaying a cached response.
`lastFrameAt` is wall-clock receipt time for diagnostics, not the presentation
timestamp delivered by the operator interface. Counters reset with `run.id`.
Errors retain useful operation context without credentials, tokens, or signed
URLs. A healthy MAVLink connection must not erase a video error, or vice versa.

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
same activation. Total cloud execution is at most eight hours from activation,
including retries, replacements, and publication. Only a subsequent verified
inactive-to-active transition permits a fresh activation budget.

The controller must compare the current run and activation before every write,
use version-conditional shadow updates, and resample after conflicts. Samples
must match `runtime.runId == run.id` and the currently assigned MicroVM. Changing
run identity clears the old endpoint and sample before publishing the new run.
Late responses from superseded runs cannot restore either. Orphan termination
and launch reconciliation remain controller responsibilities.

The JSON Schema checks structure and lifecycle/endpoint constraints. Dynamic
identity equality, monotonic deadlines, elapsed time, freshness, and conditional
write authorization are controller/runtime invariants, to be implemented and
tested in their owning issues. A valid JSON document alone proves none of them.

Readers retain both identity and freshness. Shadow `timestamp` is not evidence
that every nested status was sampled then. Attachment discovery must verify
current assignment, active device lifecycle, unexpired deadline, and live
authenticated endpoint rather than trusting a stored URL or sample alone.
The runtime polls authority every two seconds and stops after fifteen seconds
without verification. Stale assignment or shutdown releases control and denies
usable attachment. Attachment uses short-lived, port-scoped AWS authentication,
one manual attachment, and the existing cloud session/lease.

## Device and Office boundaries

Rig/witness remain device lifecycle authorities. Agent status is absent from
capabilities and REDCON rules; it cannot make a device born, available, or ready.
Office reads the optional JSON in TBot Debug independently of ordinary device
shadows, and isolates missing/read-error states. It does not use this diagnostic
sample to grant control, determine REDCON, or block normal device operation.

Observation remains the operator default. Explicit control acquires a free
board lease with `takeover=false` and permits full MAVLink, including pre-arm
traffic. The session retains control across arm/disarm/re-arm; client inactivity,
disconnect, WebRTC/lease loss, lifecycle shutdown, or process shutdown releases
it, without automatic reacquisition. See the
[agent design](../components/agent.md) and [board protocol](board-mavlink.md).
