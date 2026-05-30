---
id: doc-15
title: 'Milestone: MQTT5 retained message expiry'
type: guide
created_date: '2026-05-30 08:16'
updated_date: '2026-05-30 08:16'
---
# Milestone: MQTT5 Retained Message Expiry

## Outcome
MQTT transport code uses MQTT 5 explicitly where the repository owns a real MQTT client session, and dynamic retained AWS IoT board state expires at the same freshness boundary already enforced by software.

## Scope
- Unit board daemon MQTT packet implementation and retained publish policy.
- Raspi rig MQTT client wrapper and SparkplugManager retained board-state subscriptions.
- Shared Python AWS MQTT helper migration to MQTT5.
- Office verification for its existing MQTT5 client path.
- Durable docs for the retained message expiry policy.

Out of scope: MQTT topic renames, payload schema changes, Sparkplug metric changes, IAM topic ARN changes, Thing Shadow ownership changes, Lambda deployment topology changes, and firmware changes.

## Exit Criteria
- MQTT5 is explicit in unit daemon, rig MQTT wrapper, shared Python helper, and office verification.
- Dynamic retained AWS IoT state topics have broker-side message expiry equal to the configured capability TTL.
- Descriptor retained topics remain unexpired.
- Exact board capability-state subscriptions allow AWS IoT retained replay per inventoried device.
- Tests and rollout notes cover stale retained messages from prior releases.
