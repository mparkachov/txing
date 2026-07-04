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

Does not cover: Fargate/ECS cost of awake cloud-mcu devices (intended REDCON 3 spend), REDCON semantics or born/dead rules, witness redesign, the mac device milestone (m-1), or AWS Budgets setup itself (documented as an operator recommendation only).

Accepted tradeoff (business decision): newly registered devices may take up to 300 seconds to appear on raspi/local rigs; a rig restart or a REDCON 4-to-1 cycle forces an immediate refresh. Command latency is unaffected because commands are event-driven on all paths.

## Cost targets (idle-awake, list prices, no free tiers)

- `raspi`/`local` rig: from ~$0.65/month to <= ~$0.10/month.
- `cloud` rig: from ~$4-5/month per sleeping cloud-mcu device to <= ~$0.50/month per device.
- REDCON 4 costs remain the reference floor (~$0.01 raspi/local, ~$0 cloud).

## Implementation tasks

- `TASK-23.1` - raspi and local rigs idle at REDCON 1 for pennies
- `TASK-23.2` - cloud rig ticks are change-aware and redcon-paced
- `TASK-23.3` - rig cost posture is documented and measured

## Acceptance summary

The milestone is complete when a counted soak shows idle-awake recurring operations at or below the targets for both rig families, REDCON command convergence and lifecycle projections are demonstrably unchanged, witness and office behavior are unaffected, and the cost posture (including force-refresh and the budget guardrail recommendation) is documented for operators.

## Required references

- Architecture spec: `backlog/docs/architecture/rig-idle-cost-parity/doc-25 - Rig-REDCON-1-idle-cost-parity-architecture.md`
- Parent milestone task: `TASK-23`
- `rig/internal/registry/registry.go`, `rig/internal/rigconfig/config.go`
- `devices/cloud-mcu/lambda/internal/cloudmcu/cloudmcu.go`
- `docs/sparkplug-lifecycle.md`, `docs/components/rig.md`
