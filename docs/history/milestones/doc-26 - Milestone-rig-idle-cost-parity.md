---
id: doc-26
title: 'Milestone: rig idle cost parity'
type: specification
created_date: '2026-07-04 16:29'
updated_date: '2026-07-04 16:31'
tags:
  - rig
  - cost
  - milestone
---
# Milestone: rig idle cost parity

## Goal

All rigs run at REDCON 1 permanently with recurring AWS costs close to REDCON 4 while no managed device is awake. Cost stops being the reason to park rigs at REDCON 4.

## Scope

Covers the standalone rig manager's inventory loop (`raspi`/`local`: 300-second default, single-query refresh, catalog caching, quiet logs) and the cloud rig tick chain (change-aware shadow writes and Sparkplug publication, redcon-paced tick cadence, cached identity lookups), plus operator documentation and before/after measurement evidence.
It also covers explicit daemon enablement from `daemon.env` so local and raspi
rigs can keep the manager-only default and turn BLE or Thread on by config
edit plus restart.

Does not cover: Fargate/ECS cost of awake cloud-mcu devices (intended REDCON 3 spend), REDCON semantics or born/dead rules, witness redesign, the mac device milestone (m-1), or AWS Budgets setup itself (documented as an operator recommendation only).

Accepted tradeoff (business decision): newly registered devices may take up to 300 seconds to appear on raspi/local rigs; a rig restart or a REDCON 4-to-1 cycle forces an immediate refresh. Command latency is unaffected because commands are event-driven on all paths.

## Cost targets (idle-awake, list prices, no free tiers)

- `raspi`/`local` rig: from ~$0.65/month to <= ~$0.10/month.
- `cloud` rig: from ~$4-5/month per sleeping cloud-mcu device to <= ~$0.50/month per device.
- REDCON 4 costs remain the reference floor (~$0.01 raspi/local, ~$0 cloud).

## Measurement evidence

Monthly extrapolations use a 30-day month and the architecture spec's
2026-07 us-east-1-equivalent list-price yardstick with no free tiers. Counts
below are recurring idle-awake operations; one-time startup, changed-state, and
operator-command work is intentionally excluded.

| Rig family | Before | After evidence | Monthly extrapolation | Target |
| --- | --- | --- | --- | --- |
| `raspi`/`local` | 30 s inventory loop: 86,400 refreshes/month. Each refresh performed one `SearchIndex`, `DescribeThing` for the rig plus each device, SSM catalog reads, and an unchanged-refresh CloudWatch info line. For the 4-device soak shape this is 86,400 `SearchIndex` plus about 432,000 recurring `DescribeThing` calls/month, matching the architecture baseline of about $0.65/month including about 12 MB/month of logs. | 2026-07-06 raspi debug soak showed unchanged refresh counters `searchIndex=2/3/4/5`, `describeThing=1`, `ssmReads=13`, `devices=4`, including across a live REDCON 1 -> 4 -> 1 transition. That proves one additional `SearchIndex` per 300 s refresh and no recurring per-device `DescribeThing` or SSM reads during the soak. | 300 s inventory loop: 8,640 refreshes/month. The recurring metered fleet-indexing cost is 8,640 `SearchIndex` calls/month, about $0.04/month at $0.05/10k. Recurring unchanged-refresh `DescribeThing` and info-log ingestion are 0; standard SSM catalog reads are cached and not a metered cost in this yardstick. | <= ~$0.10/month met. |
| `cloud` sleeping `cloud-mcu` device | Minute schedule fanned out 10 offsets/device: 432,000 ticks/device/month. Each tick performed registry/shadow work and a device DBIRTH/DDATA publish that triggered IoT rules, witness Lambda, and sparkplug shadow projection; the architecture baseline records about 2.2M shadow/registry operations and about $4-5/device/month. | 2026-07-06 live soak showed cloud-mcu invocations once per minute at 09:28:53Z, 09:29:53Z, and 09:30:53Z. For `cloud-mcu-ph4p98`, unchanged `power` and `sparkplug` shadows stayed at July 06, 2026 10:29:25 UTC+02, `sqs` stayed at July 05, 2026 06:58:18 UTC+02, and there were no recurring unchanged-device shadow writes. Unit coverage also asserts no recurring device DBIRTH/DDATA or witness-facing projection movement after stable state is born. | Sleeping cadence is 43,200 ticks/device/month, a 90% tick reduction. Recurring unchanged `UpdateThingShadow`, device DBIRTH/DDATA, IoT rule, witness invocation, and sparkplug-shadow projection counts are 0 after the stable state is born. The remaining minute tick/SQS/Lambda/read path is pennies and stays below the <= ~$0.50/month/device target. | <= ~$0.50/month/device met. |

## Implementation tasks

- `TASK-23.1` - raspi and local rigs idle at REDCON 1 for pennies
- `TASK-23.2` - cloud rig ticks are change-aware and redcon-paced
- `TASK-23.3` - rig cost posture is documented and measured
- `TASK-23.4` - rig daemons are enabled from daemon.env

## Acceptance summary

The milestone is complete when a counted soak shows idle-awake recurring operations at or below the targets for both rig families, REDCON command convergence and lifecycle projections are demonstrably unchanged, witness and office behavior are unaffected, and the cost posture (including force-refresh and the budget guardrail recommendation) is documented for operators.

## Required references

- Architecture spec: [Rig REDCON 1 idle cost parity architecture](../architecture/doc-25%20-%20Rig-REDCON-1-idle-cost-parity-architecture.md)
- Parent tracking issue: [#76 — TASK-23](https://github.com/mparkachov/txing/issues/76)
- `rig/internal/registry/registry.go`, `rig/internal/rigconfig/config.go`
- `devices/cloud-mcu/lambda/internal/cloudmcu/cloudmcu.go`
- `docs/sparkplug-lifecycle.md`, `docs/components/rig.md`

## GitHub issue references

- [#76 — Milestone: rig REDCON 1 idle cost parity](https://github.com/mparkachov/txing/issues/76) (migrated from `TASK-23`)
- [#87 — rig daemons are enabled from daemon.env](https://github.com/mparkachov/txing/issues/87) (migrated from `TASK-23.4`)
