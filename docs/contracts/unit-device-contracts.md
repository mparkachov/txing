# Unit device contracts

This document collects durable contracts for the current `unit` device type.
Read it before changing Thing Shadow contracts, BLE behavior, MQTT topics, board
video, rig/device ownership boundaries, MCU power behavior, or runtime failure
semantics.

## Source-of-truth documents and schemas

- Thing Shadow schema source of truth for the current `unit` device type:
  `devices/unit/aws/*-shadow.schema.json`.
- Current rig-era shadow plus BLE compatibility contract:
  `devices/unit/docs/device-rig-shadow-spec.md`.
- Sparkplug lifecycle design: `docs/sparkplug-lifecycle.md`.

## Ownership boundaries

- `rig` owns the `sparkplug`, `device`, and `mcu` named shadow contracts.
- `txing-unit-daemon` owns the `board` named shadow contract for the `unit`
  device type.
- `txing-unit-daemon` remains the only publisher of `board.*` Thing Shadow
  updates.
- `txing-unit-hardware-worker` owns board-local motor hardware access and local
  failsafe neutralization only. It does not own MCP sessions, REDCON policy,
  cloud publication, Thing Shadow state, or actuator authorization.

## Runtime reliability

Rig, MCU, board, and cloud-facing systems are correctness-critical.

- Rig runtime stability is a hard requirement: `rig` services are not
  user-serviced applications.
- All rig network, BLE, AWS, IPC, and supervisor-facing loops must tolerate
  transient failures with bounded retries, backoff, and log throttling where
  repeated failures are expected.
- Retry paths must avoid resource churn or leaks. Reuse long-lived
  clients/managers where the underlying library supports it.
- Prefer deterministic behavior, bounded retries, graceful degradation,
  operational observability, rollback safety, protocol consistency, and state
  consistency.
- Avoid hidden retry storms, unbounded loops, silent state divergence,
  unnecessary concurrency, fragile timing assumptions, and repeated noisy logs.

## Board video

- Board video is a headless network-service design. Do not assume any GUI, local
  browser, or desktop session on the board.
- For the current `unit` device type, `REDCON 2` means board and MCP are
  available while video is unavailable or not ready. `REDCON 1` means board,
  MCP, and video are available.
- When BLE confirms REDCON `4` / `power=false`, Sparkplug projection clears
  board-owned capabilities and does not reuse stale retained board state on the
  next wake. Fresh board daemon state must arrive before `board`, `mcp`, or
  `video` become available again.
- Stale `board.power=true` or `wifi.online=true` must not be treated as
  authoritative after a hard board power cut.
- The current implementation uses plain AWS KVS WebRTC signaling as the live
  operator video path.
- Video-capable devices keep one AWS KVS signaling channel as the browser media
  path. Multiple browser viewers may observe through separate WebRTC peer
  sessions on that channel; this is distinct from MCP active control.
- `txing-unit-daemon` writes local runtime state, receives coarse sender
  readiness over BoardVideoBridge gRPC, publishes retained video
  descriptor/status topics for `rig`, and mirrors descriptor/status into the
  `video` named shadow for readers.
- `rig` consumes retained MQTT video service topics for REDCON derivation.
- The browser operator path uses the AWS KVS viewer flow, not a board-local
  iframe page.
- The repo ships the native sender in-tree. The sender and daemon run as
  separate systemd services and communicate through the local BoardVideoBridge
  contract.
- The repo ships the native hardware worker in-tree. The worker and daemon run
  as separate systemd services and communicate through the local UnitHardware
  gRPC contract documented in `docs/contracts/unit-hardware-worker.md`.
- Browser-to-board motion control uses board MCP tools with a lease hard gate.
- The legacy raw `<device_id>/board/cmd_vel` path is removed.

## Board MCP and active control

- REDCON `1`: MCP is WebRTC data-channel only on the board video KVS media
  session, with label `txing.mcp.v1`.
- REDCON `2`: MCP is MQTT JSON-RPC only.
- The daemon maintains one active control slot. Many MCP sessions may observe,
  but only the active session may execute actuator tools.
- Browser drive input must not silently take over from another active session;
  takeover is explicit.
- `control.activate`, `takeover`, session identity, transport, and epoch
  enforcement are the active-control protocol baseline.
- MCP status publishes `activeControl=null` when no session owns actuator
  authority, or an active-control object with `sessionId`, `actor`,
  `transport`, `sinceMs`, `expiresAtMs`, and `epoch`. Office consumes this
  status to distinguish observers from the active controller.

## Power terminology

- `power=true` means the device is in the wakeup state.
- `power=false` means the device is in the sleep state.
- In the sleep state, the MCU stays in RTC-driven low-power idle between
  periodic rendezvous wakeups.
- The sleep-state rendezvous interval is every `5 s`: the MCU wakes briefly,
  refreshes BLE state, advertises for a bounded window, and returns to low-power
  idle if no BLE session is needed.
- Use `wakeup state` and `sleep state` when describing the external device power
  contract.
- Distinguish the external sleep/wakeup contract from the firmware's internal
  `Wake` step inside the sleep-state rendezvous cycle.
