---
id: doc-25
title: Rig REDCON 1 idle cost parity architecture
type: specification
created_date: '2026-07-04 16:29'
updated_date: '2026-07-04 16:30'
tags:
  - rig
  - cost
  - architecture
---
# Rig REDCON 1 idle cost parity

## Goal

All rig types (`raspi`, `local`, `cloud`) can stay at REDCON 1 permanently, and while no managed device is awake ("idle-awake") their recurring AWS cost stays close to the REDCON 4 cost. REDCON 4 remains the deep-sleep posture, but cost must no longer be the reason to park a rig there.

Business decision baked in: device registration is rare, so a new device may take up to 5 minutes to appear in inventory; a rig restart (or an NCMD 4 -> 1 cycle) forces an immediate refresh.

## Measured baseline (2026-07, us-east-1-equivalent list prices, no free tiers)

Idle-awake monthly cost today:

- `raspi`/`local` rig: ~$0.65. Dominated by the 30 s inventory loop: 1 fleet-indexing `SearchIndex` query ($0.05/10k) + `DescribeThing` for the rig and each device ($1.25/M, 1 KB blocks) + SSM catalog pages (free at standard throughput) per tick; plus ~12 MB/month CloudWatch info logs.
- `cloud` rig: ~$4-5 per sleeping cloud-mcu device. The minute schedule fans out 10 SQS ticks per device (offsets 0,6,...,54 s); every tick unconditionally runs `DescribeThing` + `GetThingShadow(power)` + `UpdateThingShadow(sqs)` + `UpdateThingShadow(power)` + a `DBIRTH`/`DDATA` publish, and each publish triggers the rules engine + witness Lambda + a sparkplug shadow write. ~432k ticks and ~2.2M shadow/registry operations per device per month, all change-blind.
- REDCON 4 reference: `raspi`/`local` ~$0.01 (node MQTT session only); `cloud` ~$0 (schedule disabled; idle SQS poller inside the always-free tier).

## Cost target (acceptance yardstick)

Idle-awake, sustained:

- `raspi`/`local`: <= ~$0.10/month (>= 85% reduction) - at most one fleet-indexing query per 300 s, no recurring shadow writes, catalog reads cached.
- `cloud`: <= ~$0.50/month per sleeping device (>= 90% reduction) - shadow writes only on state change, at most one liveness publish per device per minute, no change-blind registry reads.
- Unchanged: REDCON command convergence latency (commands are event-driven on all paths), office UX, Sparkplug lifecycle contract (`docs/sparkplug-lifecycle.md`), witness ownership.

## Design directions (per rig type)

### raspi/local (`rig/` standalone daemons)

1. Inventory cadence: default `TXING_INVENTORY_INTERVAL_SECONDS` 30 -> 300 (code default in `rig/internal/rigconfig/config.go`, `rig/rig-daemon.env.template`, docs). Startup and REDCON 4->1 resume already refresh immediately; document restart as the manual force-refresh.
2. Kill the per-device `DescribeThing` fan-out in `rig/internal/registry/registry.go` `LoadInventory`: the fleet-indexing `SearchIndex` document already carries thing name, type, and attributes; use it directly (or cache `DescribeThing` results keyed by thing version) so one query per tick is the steady state.
3. Cache the SSM type catalog across ticks (today `typeCache` lives inside one `LoadInventory` call). Catalog changes are deploy-time events; a long TTL or invalidation on inventory membership change is sufficient.
4. Logging: stop emitting a CloudWatch info line per unchanged refresh (log on change or demote to debug); 14-day retention stays.

### cloud (`devices/cloud-mcu/lambda`, `HandleTickWithNow` / `HandleScheduleWithNow`)

1. Change-aware shadow writes: read once, write `sqs` and `power` shadows only when the rendered reported state differs from the current one. At idle this removes ~3 writes per tick per device.
2. Change-aware Sparkplug publication with slow liveness: publish `DDATA` when redcon/capabilities change, plus at most one liveness `DDATA` per device per minute (today: every 6 s). Witness merges `DDATA`, so consumers are unaffected; each publish removed also removes one rules-engine trigger, one witness invocation, and one witness shadow write.
3. Redcon-aware tick cadence: sleeping devices get one tick per minute (single offset); awake (REDCON 3) devices keep the 6 s offsets for ECS reconciliation responsiveness. `TickOffsetsSeconds` selection moves from a constant to per-device state known by the scheduler.
4. Identity churn: `validateDeviceIdentity`'s per-tick `DescribeThing` should be cached (tick payloads originate from the scheduler's own discovery moments earlier).
5. Options to evaluate, not mandated: slowing the `NBIRTH` refresh below 1/min (interacts with the deferred cloud NDEATH design in `docs/sparkplug-lifecycle.md` - do not change the liveness contract silently); self-adjusting the EventBridge schedule rate when the fleet is fully asleep.

### Witness

No redesign. Witness cost is proportional to messages published; fixing publication frequency at the source is the lever. (A change-skip inside witness would require a shadow read per message - no saving.)

## Non-goals

- Fargate/ECS cost of awake cloud-mcu devices (that is the intended REDCON 3 spend; posture discipline covers it).
- Changing REDCON semantics, the born/dead rules, or witness shadow ownership.
- The mac device milestone (m-1) - unaffected; the mac daemon is event-driven and adds no polling.
- Billing guardrails (AWS Budgets alert) - operator action, noted for the runbook, not repo code.

## Validation approach

- Unit tests asserting no-write/no-publish on unchanged tick state (cloud) and single-query inventory refresh (rig).
- A counted soak: run each rig idle-awake for a fixed window and count AWS calls (CloudWatch metrics for Lambda invocations / rules triggered; local counters or debug logs for the rig daemon) before/after; extrapolate to the monthly target.
- Contract checks: REDCON command round-trip latency unchanged; new device appears within 300 s on raspi/local; rig restart refreshes immediately; office projections unchanged.

## References

- `rig/internal/registry/registry.go` (LoadInventory, SearchIndex, type cache)
- `rig/internal/rigconfig/config.go`, `rig/rig-daemon.env.template` (interval default)
- `devices/cloud-mcu/lambda/internal/cloudmcu/cloudmcu.go` (HandleScheduleWithNow, HandleTickWithNow, TickOffsetsSeconds)
- `docs/sparkplug-lifecycle.md` (liveness/NBIRTH contract), `docs/components/rig.md`
- Pricing: AWS IoT Core (messaging/shadow/registry/rules), IoT Device Management (fleet indexing), CloudWatch Logs

## GitHub issue references

- [#76 — Milestone: rig REDCON 1 idle cost parity](https://github.com/mparkachov/txing/issues/76) (migrated from `TASK-23`)
- [#77 — raspi and local rigs idle at REDCON 1 for pennies](https://github.com/mparkachov/txing/issues/77) (migrated from `TASK-23.1`)
- [#83 — cloud rig ticks are change-aware and redcon-paced](https://github.com/mparkachov/txing/issues/83) (migrated from `TASK-23.2`)
- [#86 — rig cost posture is documented and measured](https://github.com/mparkachov/txing/issues/86) (migrated from `TASK-23.3`)
- [#87 — rig daemons are enabled from daemon.env](https://github.com/mparkachov/txing/issues/87) (migrated from `TASK-23.4`)
