# Witness agent shutdown watch

The operator approved this independent repair path on 2026-10-29 for #168.
Normal shutdown belongs to the C++ controller. Witness checks that cloud agent
compute actually goes away if that path fails, after a grace period. This is a
stop-only exception in the existing Go witness Lambda; it is not a second agent
controller or shadow projector.

## Ownership and timing

- The C++ controller remains the only operational writer of the `agent` shadow.
  Witness reads it, describes MicroVMs and requests termination. It cannot launch
  an agent, grant an assignment, extend an activation, or reset an expired budget.
- Witness still projects only Sparkplug MQTT into the `sparkplug` shadow. A
  bounded watch check follows successful projection, including unchanged metrics;
  watch failure does not turn a successful projection into a failed invocation.
- MQTT traffic is not periodic or guaranteed. A separate one-minute EventBridge
  rule invokes the same witness Lambda even when devices and the controller are
  silent. Its state does not follow the controller's automation switch.
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
  invocation and service latency add to this interval; it is not a strict
  wall-clock SLA. A termination request is not evidence of terminal state.

## Scope and failure handling

Configure witness with the same dedicated Frankfurt image name as the agent
stack. Inventory covers every version of that image. Get and terminate IAM
permissions are scoped to its image ARN; the watch has no run, resume, token,
or pass-role permissions and receives no agent-shadow-write interface.
The existing witness role retains Thing-level shadow-update permission for
Sparkplug projection. HTTPS shadow IAM actions authorize the Thing ARN rather
than a per-shadow ARN; appending `/agent` or `/sparkplug` would not implement
shadow-specific isolation. Controller-only agent writes remain an application
ownership rule. See the [AWS shadow REST authorization examples](https://docs.aws.amazon.com/iot/latest/developerguide/device-shadow-rest-api.html).

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
Lambda error metrics; ordinary grace/terminal-state waiting reports incomplete
without adding asynchronous retry traffic. Projection-path failures are logged
and deferred to the schedule. Do not log tokens, credentials, launch payloads,
or complete shadows.

This design repairs controller-specific shutdown failures while witness,
EventBridge, IoT reads and the MicroVM termination API are available. It shares
those AWS dependencies with normal control. A shared service outage can delay
termination until recovery or the platform lifetime limit. The operator's
approved delay is not an unconditional guarantee during an AWS outage.

The operator explicitly limited assigned-run shutdown evidence to an off agent
shadow or its expired deadline on 2026-10-29. If the controller fails before
recording an early device shutdown and leaves a non-expired `running`
assignment, witness preserves it until the shadow becomes off or the deadline
expires. Sparkplug inactivity alone does not authorize watch termination.

## Manual rollout and acceptance

1. Bump `release/versions/lambda` above its current published version before
   publishing the changed witness artifact. Build/release the static Linux ARM64
   Go bootstrap through the existing shared Lambda release workflow. Rebuild the
   C++ controller with the persistent stop timestamp before enabling the watch.
2. Keep agent automation disabled. Publish the release-built witness code using
   the established operator workflow; `just release::publish lambda` updates all
   three shared Go runtime functions, so review their release contents first.
3. Run `just witness::deploy <environment-stack> <agent-image-name>` manually to
   configure the scoped permissions, environment and minute rule. The image name
   must match the agent stack's `ImageName`. Omitting the second argument keeps
   the existing CloudFormation parameter; a first deployment defaults to
   `disabled`. Do not disable the watch as part of ordinary controller shutdown.
4. On a secured, lifted TBot, record an operator-run test with the primary
   controller unavailable: an off assignment remains during the grace period,
   is sent for termination by witness afterward, and reaches `TERMINATED` in a
   later service read. Repeat with a deadline that expires while the shadow
   still says `running`, and an aged unassigned instance of the dedicated image.
   Record the image/version, run identity, timestamps and actual terminal state.
5. Verify that a healthy run and a reactivated replacement survive, individual
   media errors cause no termination, Sparkplug projection still works when the
   watch's APIs fail, unreadable shadows defer orphan cleanup, and the schedule
   works without MQTT traffic. A non-expired running assignment must also survive
   Sparkplug inactivity alone. Check pagination and retry behavior under load.
6. Enable agent automation only after the existing artifact, physical and live
   acceptance gates and these watch checks pass. Before changing the dedicated
   image identity, disable launches and manually drain/confirm all old-image
   instances; update both stacks together. If repair fails, inspect witness
   errors/permissions and perform the documented manual drain.

Prepared code, loopback API tests and an ARM64 build are not live AWS acceptance.

### Isolate the controller during the orphan test

Binding an image while agent automation is disabled enables the controller's
termination-only minute schedule. A successful cleanup with that schedule
running does not independently prove witness repair. For operator-run witness
acceptance, pause only the controller repair rule and temporarily set the
controller's reserved concurrency to zero to block queued asynchronous retries.
Wait longer than its configured 120-second timeout for an invocation already
running to finish. Leave witness's independent schedule enabled throughout.
These are manual fault-injection actions, not changes to the normal concurrency
requirement of one.

The first orphan test can keep the device at REDCON 4 and leave its stopped
agent shadow unmodified. Deliberately launch one instance of the dedicated image
with unique run/activation identities that have no persisted assignment. The
production runtime must refuse device sessions; no shadow is forged to authorize
it. This controlled unassigned launch is only an acceptance fixture. Use a
600-second hosting cap and matching absolute hook deadline generated immediately
before launch, so a witness request after its 120-second grace is distinguishable
from platform expiry. Do not set an idle suspension policy.

Record AWS start time, nonterminal state during the grace, the exact witness
termination request and later `TERMINATED` state. A failed run hook, manual stop,
or platform lifetime expiry is not witness success. If it remains nonterminal
five minutes after AWS start time, record failure and stop it manually. Restore
controller concurrency to one and its repair rule only after every test VM is
confirmed terminal. Keep ordinary launches disabled. Known off/deadline cases
and healthy/replacement preservation remain separate live acceptance checks.

### Synthetic assigned-record tests

Known off/deadline branches may be exercised with administrative fixture data
on a temporary untyped IoT Thing marked `testFixture`. This Thing has no rig,
hardware, credentials or signaling channels. Its unsupported registered type
causes the production runtime to stop before opening device connections.
Fabricated records on this fixture are test inputs, not operational assignments;
they must never be installed on a real device Thing or counted as proof of
controller/device session health. The controller-only operational writer rule
and real device activation histories remain unchanged.

With the primary controller isolated and witness enabled, launch one VM for
the fixture and bind its identity to a schema-valid, version-conditional
synthetic `running` record before the orphan grace expires. Include individual
media errors, a future activation deadline and consistent run metadata. Generate
the request token and absolute deadline together immediately before launch;
validate their timestamp and remaining lifetime before binding. A failed run
hook or expired fixture does not establish watch acceptance. Observe
preservation beyond the orphan cutoff, then transition that same record to
`stopping` with its first `stopRequestedAt`. Preserve the run/activation and
reject repeated transitions that would postpone the grace. Witness must retain
it through that off-time grace and later request termination; require actual
terminal state before the hosting cap.

In a separate VM case, leave the synthetic record `running` as its deliberately
shortened absolute deadline passes. Observe preservation before deadline+120,
then a witness termination request and terminal state before the independent
hosting cap. Clear the previous off timestamp when binding the new test run.
Never extend a real activation or reset a real device's shadow for testing.
After terminal confirmation, delete only the temporary fixture's shadow and
Thing and restore controller concurrency/rule settings. These tests establish
watch behavior for stored off/deadline evidence; real healthy runs, device
streams, attachment and controller-driven lifecycle remain separate acceptance.
