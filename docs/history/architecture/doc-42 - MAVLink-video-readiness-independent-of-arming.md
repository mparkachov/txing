---
id: doc-42
title: MAVLink video readiness independent of arming
type: specification
created_date: '2026-09-05 11:00'
tags:
  - tbot
  - cyberbrick
  - mavlink
  - video
  - redcon
---

# MAVLink video readiness independent of arming

## Outcome

For every MAVLink board device, REDCON describes reachable runtime
capabilities, not whether its flight controller is armed. A healthy TBot or
Cyberbrick with working video reports REDCON 1 whether it is armed or
disarmed. The MAVLink arm state remains visible in its named shadow and remains
authoritative for flight-safety and control behavior.

## REDCON contract

TBot and Cyberbrick retain their existing transport-, power-, board-,
MAVLink-, and video-capability requirements. REDCON 1 requires all of those
capabilities, including ready video; it has no `mavlinkArmed` metric
requirement. Consequently:

| State | REDCON |
| --- | --- |
| MAVLink ready, video unavailable | 2 |
| MAVLink ready, video ready, disarmed | 1 |
| MAVLink ready, video ready, armed | 1 |

A REDCON command never arms or disarms the vehicle. Arming and disarming stay
explicit ordinary MAVLink control operations with the existing authority,
watchdog, Hold, neutral, and disarm safety rules.

## Scope and ownership

The correction applies uniformly to the current MAVLink board device types:
`tbot` and `cyberbrick`. Their manifests and generated catalog records remove
the REDCON-1 `mavlinkArmed` metric rule. The rig then projects REDCON entirely
from capability availability.

Office continues to show MAVLink arm state in the control panel. Its video
eligibility follows REDCON 1, which now represents actual video readiness
instead of vehicle arming state. No MCU, ArduPilot, MAVLink wire, certificate,
KVS signaling, or board camera behavior changes.

## Validation and rollout

Automated catalog, rig-projection, Office adapter, and documentation tests
must cover both armed and disarmed MAVLink boards with ready video reporting
REDCON 1. Existing negative cases where video or MAVLink is unavailable must
remain REDCON 2 or lower.

Rollout requires a catalog/IAM deployment followed by a restart of the Txing
Sparkplug manager. The manager caches each type-catalog record for up to one
hour, and a restart is the immediate, deterministic refresh. Re-enlistment and
an Office deployment are not required: the existing device attributes and
Office REDCON-1 video gate already have the correct shape. Existing board
release artifacts do not need replacement because the board already publishes
the required video and MAVLink capability state.

## Risks and non-goals

REDCON 1 no longer implies a vehicle is armed; operators must consult the
MAVLink control state before treating the rover as armed. This correction does
not relax the arm/disarm protocol, automatic safe-state behavior, control
lease, camera readiness, or device-specific hardware safety constraints.
