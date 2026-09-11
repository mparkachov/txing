# Rig OTBR Host Supervision And Warning Throttle

Status: approved on 2026-09-11

## Context

The production rig used for TBot recovery validation ran OTBR through a
systemd-generated wrapper for `/etc/init.d/otbr-agent`. The generated unit used
`RemainAfterExit=yes`, `GuessMainPID=no`, and `Restart=no`. After the MG24 RCP
USB path timed out, the real `otbr-agent` process exited while systemd continued
to report the wrapper unit as active. `txing-thread-connectivity` then emitted
the same failed `ot-ctl` maintenance warning every ten seconds until an
operator restarted OTBR. Once OTBR returned, the existing TBot firmware
reattached and restored its active SRP record without an MCU or rig reboot.

This is a host-runtime failure, not an MCU recovery failure. The rig needs to
observe and restart the actual OTBR process, and the Thread adapter needs to
retain a useful warning without producing an unbounded stream of duplicates.

## Outcome

An unexpected `otbr-agent` exit is visible to systemd and receives bounded
automatic restart attempts. While OTBR is unavailable,
`txing-thread-connectivity` reports the outage promptly but throttles identical
maintenance warnings. Recovery remains visible, and all existing Thread
device, REDCON, SRP, and shadow behavior is preserved.

## Ownership And Boundaries

- OTBR remains operator-installed and operator-configured host infrastructure.
  Txing does not install OTBR, choose its radio URL, or own the Thread dataset.
- The host systemd service owns only the `otbr-agent` process lifecycle. It
  runs the daemon in the foreground instead of treating a successful SysV
  start wrapper as proof that OTBR remains alive.
- `txing-thread-connectivity` remains an `ot-ctl` client. It does not call
  `systemctl`, restart OTBR, require additional privileges, or become a second
  supervisor.
- The Thread adapter continues running when OTBR is unavailable. Its existing
  offline projection and periodic discovery provide graceful degradation while
  systemd attempts host-level recovery.

## Host Supervision

The rig operations contract supplies an upstream-shaped native
`otbr-agent.service` definition that replaces the generated SysV unit. It runs
the installed `/usr/sbin/otbr-agent` directly with the existing
`/etc/default/otbr-agent` environment instead of starting a background process
through `/etc/init.d/otbr-agent`. The native unit must:

- identify the foreground daemon as `MainPID`, with `RemainAfterExit` disabled;
- restart only after an unexpected failure;
- wait 10 seconds between attempts;
- permit at most five starts in any five-minute interval, leaving the unit
  visibly failed if a persistent fault exhausts that bound; and
- preserve manual stop semantics so an operator stop does not cause a restart.

Installation remains an explicit writable-root operator action. Before
replacing the generated unit, the operator verifies the installed executable
and existing `OTBR_AGENT_OPTS`, then preserves that configuration unchanged.
The rollout includes a rollback copy of the previous unit arrangement and
checks both process identity and `ot-ctl` readiness.

`txing-thread-connectivity.service` may order itself after and weakly want
`otbr-agent.service`, but it must not require or bind to OTBR. A temporary or
persistent OTBR outage must not make systemd stop the Thread adapter.

## Warning Throttle

Thread maintenance warnings use a ten-minute duplicate window:

1. The first failure is logged immediately.
2. Repeated failures with the same error text are suppressed during the
   window.
3. The first matching failure after the window is logged with the number of
   suppressed duplicates, then begins the next window.
4. A different failure is logged immediately and begins a new series.
5. The first successful maintenance discovery after a failure series emits one
   informational recovery message with the outage duration and total
   suppressed-warning count, then clears the series.

The throttle uses elapsed monotonic time and has bounded in-memory state. It
does not change discovery or polling cadence, command error reporting, command
priority, device offline publication, or process exit behavior. Shutdown and
context-cancellation errors remain excluded from maintenance warnings as they
are today.

## Validation

Automated validation covers native-unit process tracking, restart policy,
start-rate bounds, manual-stop behavior, weak Thread-service ordering, first
warning delivery, duplicate suppression, periodic reminder counts, distinct
errors, and recovery summaries. Existing rig Thread scheduler and protocol
tests remain green.

Manual validation on a rig confirms that terminating the actual `otbr-agent`
process makes the service fail and restart it, `ot-ctl` becomes ready again,
and a Thread device restores active child/SRP evidence without restarting the
MCU or the rig daemons. A persistent startup failure is also checked to ensure
the systemd start-rate bound stops a restart storm.

## Risks

- The unit assumes the production host paths `/usr/sbin/otbr-agent` and
  `/etc/default/otbr-agent`. The operator must verify both before activation.
- Restarting OTBR temporarily removes Thread reachability and can produce
  expected offline/online lifecycle transitions.
- Warning suppression can hide volume if recovery reporting is incomplete;
  reminder counts and a recovery summary preserve that evidence.

## Non-Goals

- Installing, upgrading, configuring, or patching OTBR or its RCP firmware.
- Changing the Thread dataset, radio URL, SRP configuration, or device
  firmware.
- Letting a txing daemon invoke systemd or restart host services.
- Changing maintenance intervals, CoAP retry behavior, REDCON semantics,
  shadows, MQTT topics, or cloud resources.
- Automatically deploying the unit or restarting a production rig.
