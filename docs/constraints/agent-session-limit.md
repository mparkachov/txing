# Current-stage agent session limit

Decision: **50 minutes (3000 seconds) maximum**, approved by the operator after
internal discussion on 2026-10-23. This replaces the earlier eight-hour project
budget for the current stage. Longer sessions require another explicit decision
and validation of the renewal path. The AWS service's lifetime ceiling does not
change this project limit.

## Finding and evidence

The TBot board's IoT role issues credentials for 3600 seconds. Its KVS runtime
refreshes five minutes before expiration, replacing the MAVLink and video KVS
sessions. The MAVLink worker reports `ready=false` during replacement; the
daemon publishes that capability as unavailable. Both TBot REDCON 1 and 2 require
MAVLink, so the rig's rules derive REDCON 3 and the agent's existing lifecycle
rule initiates shutdown. Video attachment can also end during this renewal.

On 2026-10-22, CloudTrail records successful board-role assumptions at 14:14:37,
15:09:37 and 16:04:37 CEST, exactly 55 minutes apart. Board logs record KVS peer
closure/recreation and the seventh agent peer disconnect during the final
renewal. The agent subsequently reports `device inactive or dead`; the later
retained projection has returned to REDCON 1. The board boot ID is unchanged.
Renewal, session replacement, peer disconnect and worker shutdown are recorded;
the intermediate capability/REDCON payloads were not retained and that part of
the explanation is inferred from source. This is separate from the Wi-Fi/MMC
kernel fault tracked in [#171](https://github.com/mparkachov/txing/issues/171).

Detailed evidence and provenance are in the
[MicroVM acceptance record](../agent-microvm-acceptance.md#seventh-board-capture--scheduled-renewal-interrupts-lifecycle).
The board credential/session repair is deferred at this stage.

## Meaning of the limit

- Fifty minutes is an upper bound, not a guarantee of uninterrupted operation.
  An already-running board can reach its credential-renewal point sooner. A new
  agent process does not restart the board's credential clock. Earlier lifecycle
  loss, unverified state, connection failure or authority loss still takes
  effect normally; the limit does not mask those conditions.
- New disposable MicroVM requests use `maximumDurationInSeconds=3000`. Preserve
  the historical requests and their actual larger caps as evidence; a new
  prepared request is not proof that the fifty-minute cutoff ran in AWS.
- The planned controller persists at most fifty minutes per device activation,
  including replacements, retries and publications. Each replacement receives
  only the remaining budget. Expiry releases control and stops cloud operation;
  a continuously active device cannot obtain automatic rollover. This controller
  enforcement and accelerated boundary acceptance remain later milestone work.
- Native foreground sessions have the same supported operational ceiling; the
  operator ends them by fifty minutes. This documentation does not add an
  automatic timer to the current native command.

## Effect on #165 acceptance

The required credential evidence remains actual execution-role tuple rotation,
external temporary-session metadata, continued telemetry/video after rotation,
and secret-free diagnostics. A provider-call counter alone is insufficient.
Successful initial/reopened authenticated attachment, independent streams and
ICE evidence, more than fifteen minutes without attachment, snapshot/build
provenance and operator termination are still required.

The earlier extended test requiring at least a minute of media beyond the
original one-hour execution-role expiration is outside this stage's limit and
is superseded. Its failed audit and the later board interruption remain in the
record. Do not relabel them as successful renewal-through-expiration evidence.
Re-audit the existing seventh-run observations inside fifty minutes of actual
MicroVM start; no additional long run is required if those criteria pass.

The historical seventh VM had a 7200-second hosting cap. Its bounded observations
can establish feasibility under this decision, but do not demonstrate automatic
termination at 3000 seconds. Future requests must carry the shorter cap; later
controller/released-cloud acceptance must exercise the duration boundary.

No board installation, custom service, lifecycle debounce, automatic restart,
controller deployment or AWS mutation is authorized by this documentation.
