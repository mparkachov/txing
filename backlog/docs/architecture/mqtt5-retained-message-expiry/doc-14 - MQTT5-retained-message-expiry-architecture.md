---
id: doc-14
title: MQTT5 retained message expiry architecture
type: specification
created_date: '2026-05-30 08:15'
updated_date: '2026-05-30 08:16'
---
# MQTT5 Retained Message Expiry Architecture

## Goal
Make all real MQTT client sessions explicit MQTT 5 clients and attach MQTT5 message expiry to dynamic retained AWS IoT messages whose software TTL already defines freshness. Preserve current topic names, payload schemas, Sparkplug semantics, shadow ownership, IAM topic resources, and deployment topology.

## Current State
- `devices/unit/daemon` owns board/MCP/video retained AWS IoT publications through a custom mTLS MQTT encoder that currently sends MQTT 3.1.1 packets and retained messages without broker-side expiry.
- `rig/internal/mqttx` uses `github.com/eclipse/paho.mqtt.golang`, an MQTT 3 client, for Sparkplug and shadow update forwarding.
- `shared/aws/python/src/aws/mqtt.py` wraps AWS IoT WebSocket MQTT 3 helpers.
- `office` already uses the AWS CRT MQTT5 browser client.
- The board capability payload carries `expiresAtMs` and the rig applies `StateTTLMS=150000`, but AWS retained storage can outlive that TTL unless a newer retained publish replaces it.

## Intended Behavior
- Unit daemon MQTT packets use MQTT 5 explicitly: CONNECT protocol level 5, clean start, session expiry 0, MQTT5 property handling for CONNACK/PUBLISH/SUBSCRIBE/PUBACK, and QoS 1 behavior preserved.
- Dynamic retained unit daemon topics carry message expiry equal to `RuntimeConfig.CapabilityTTL` in seconds:
  - `txings/<device>/capability/v2/state`
  - `txings/<device>/mcp/status`
  - `txings/<device>/video/status`
- Descriptor topics remain retained without message expiry:
  - `txings/<device>/mcp/descriptor`
  - `txings/<device>/video/descriptor`
- Rig MQTT uses a MQTT5-capable Go client while preserving current reconnect, QoS 1, will, subscription, and publish behavior.
- SparkplugManager subscribes to exact board capability retained topics for inventoried devices in addition to the wildcard live subscription so retained replay works across AWS IoT reconnect/startup behavior.
- Shared Python MQTT helpers use AWS IoT MQTT5 builders and expose optional message expiry for retained publishes.

## Risks And Boundaries
- Changing MQTT protocol version and retained message expiry changes operational semantics and must stay scoped to the listed clients/topics.
- Existing retained messages that were published without expiry are replaced only when the same topic is republished; stale orphaned topics require manual AWS IoT retained-message cleanup if they matter.
- Local rig IPC retained messages are not AWS retained MQTT and remain governed by existing in-memory replay and `observedAtMs` logic.
- Runtime Lambda Sparkplug publication through IoT Data Plane is not a persistent MQTT client session and is not part of the MQTT client migration.

## Validation
- Unit daemon tests cover MQTT5 packet encoding/parsing and retained expiry assignment.
- Rig tests cover MQTT5 wrapper behavior at the interface level and exact retained board-state subscriptions per inventory.
- Shared Python tests cover MQTT5 publish retain plus message expiry propagation.
- Office tests confirm the existing MQTT5 browser path remains intact.
