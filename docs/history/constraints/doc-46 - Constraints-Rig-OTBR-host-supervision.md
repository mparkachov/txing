# Constraints: Rig OTBR Host Supervision

## Ownership

- OTBR remains external, operator-installed host infrastructure.
- Systemd is the only OTBR process supervisor.
- `txing-thread-connectivity` must not invoke `systemctl`, signal
  `otbr-agent`, mutate OTBR configuration, or gain privileges for recovery.
- Txing-owned installation instructions may replace an ineffective generated
  SysV unit only through an explicit manual operator step.

## Supervision

- The service must execute `otbr-agent` in the foreground so it becomes the
  systemd `MainPID`. A start wrapper exiting successfully is not durable
  liveness evidence.
- Unexpected exits use `Restart=on-failure` with a 10-second delay.
- Starts are limited to five per five-minute interval.
- An explicit operator stop must remain stopped.
- `txing-thread-connectivity` may weakly want and order after OTBR, but it must
  remain running during an OTBR outage.
- A persistent OTBR fault must become a visible failed unit, not an unbounded
  restart loop.

## Warning Throttle

- The first maintenance failure must be logged immediately.
- Identical error text is logged no more than once per ten minutes; reminder
  logs include the number of suppressed duplicates.
- A distinct error is immediately visible and begins a new throttle series.
- The first successful discovery after failures logs one recovery summary and
  clears the series.
- Throttle state is bounded and in memory only. It must not create files,
  retained state, timers that outlive the process, or a new dependency.
- Command failures are never covered by the maintenance-warning throttle.

## Compatibility And Operations

- Do not change discovery/poll intervals, CoAP attempts/timeouts, REDCON
  normalization, device lifecycle publication, MQTT topics, shadows, Thread
  dataset, or MCU behavior.
- Do not automate OTBR installation, native-unit activation, daemon restarts,
  or deployment. Provide manual rollout, health-check, failure-injection, and
  rollback commands.
- Rollout must verify `/usr/sbin/otbr-agent` and preserve the existing
  `/etc/default/otbr-agent` `OTBR_AGENT_OPTS` before replacing the generated
  unit.
- No AWS mutation or firmware flashing is part of this work.
