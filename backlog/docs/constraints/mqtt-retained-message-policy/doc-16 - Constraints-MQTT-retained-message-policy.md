---
id: doc-16
title: 'Constraints: MQTT retained message policy'
type: guide
created_date: '2026-05-30 08:16'
updated_date: '2026-05-30 09:24'
---
# Constraints: MQTT Retained Message Policy

## Durable Rules
- All repository-owned MQTT client sessions that connect directly to AWS IoT must use MQTT 5 explicitly.
- Retained AWS IoT messages that represent dynamic runtime state must declare a broker-side MQTT5 message expiry when the software already defines a freshness TTL.
- Retained discovery/config descriptors should stay retained without expiry unless the descriptor publisher also refreshes them periodically before expiry.
- The current dynamic retained state expiry for unit board-owned topics is the configured capability TTL, default `150s`.
- Local rig IPC retained messages are not AWS IoT retained messages and must not be treated as broker-retained state.
- `shared/aws/python` intentionally has no MQTT client helper. Do not add
  `awsiotsdk`, `awscrt`, or AWS IoT WebSocket MQTT wrapper code there unless a
  production runtime path is explicitly approved.

## Current Topic Policy
- Expiring retained topics:
  - `txings/<device>/capability/v2/state`
  - `txings/<device>/mcp/status`
  - `txings/<device>/video/status`
- Non-expiring retained topics:
  - `txings/<device>/mcp/descriptor`
  - `txings/<device>/video/descriptor`

## Operational Note
Existing retained AWS IoT messages without expiry are replaced only when a publisher writes the same topic again. Operators may need to delete orphaned retained messages manually during rollout if the publishing device will not republish them.
