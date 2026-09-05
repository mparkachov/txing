---
id: doc-41
title: nRF54LM20A SED exponential recovery
type: specification
created_date: '2026-09-05 10:00'
---

# nRF54LM20A SED exponential recovery

## Outcome

The shared nRF54LM20A Thread firmware must recover a lost Sleepy End Device
(SED) attachment without a manual MCU power cycle. The behavior applies to
`tbot`, `power-nrf`, and future device types that opt into the shared
production SED-recovery profile.

## Recovery contract

At REDCON 4, the MCU remains a receiver-off SED (`mRxOnWhenIdle=false`) with
the existing 5000 ms poll period and D1 off. A recovery attempt must never
switch it to receiver-on (`rn`) mode.

When an attached SED loses its child role or required receiver-off link mode,
the shared firmware retries a SED-only Thread restart after these delays:

```
20 s, 40 s, 80 s, 160 s, 320 s, 600 s, then every 600 s
```

Only one recovery work item may be pending at a time. The backoff is reset only
when the SRP client receives a successful registration callback, not merely
when the Thread stack observes a child role. A fresh successful SRP
registration therefore proves both attachment and service discoverability
before normal recovery timing resumes.

REDCON 3 behavior is unchanged: it intentionally uses receiver-on `rn` mode
for active board power and immediate control. Existing diagnostic profiles that
explicitly request receiver-on recovery remain diagnostic-only and unchanged.

## Scope and ownership

The shared `devices/common/mcu/xiao_nrf54lm20a` firmware owns this behavior.
Device-owned Kconfig continues to select whether a product uses the shared
SED-only recovery policy. No rig, MQTT, Sparkplug, shadow, Thread dataset, or
CoAP protocol contract changes.

## Validation and rollout

Automated coverage must verify the delay progression, cap, retry coalescing,
SED-only link-mode invariant, and SRP-success reset condition. Existing release
and diagnostic profile builds for `tbot` and `power-nrf` must pass.

The first production field validation is manual on TBot: flash the prepared
production artifact, leave it at REDCON 4 for several days, and confirm that a
forced or naturally observed attachment loss re-registers SRP and returns to
Office without a rig or MCU reboot. Flashing remains an operator action; no
firmware programming is automated.

## Risks and non-goals

Repeated detached-state retries consume more energy than the previous
three-attempt limit. The ten-minute cap bounds that cost while avoiding a
permanent offline state. This work does not add receiver-on fallback, reset the
MCU, alter REDCON behavior or poll period, change the Thread network, or solve
independent RF, battery, or hardware faults.
