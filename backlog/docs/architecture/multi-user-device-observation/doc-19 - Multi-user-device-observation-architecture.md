---
id: doc-19
title: Multi-user device observation architecture
type: specification
created_date: '2026-06-17 07:09'
updated_date: '2026-06-17 07:10'
---
# Multi-user device observation architecture

## Goal

Allow multiple signed-in Office users to open the same device and observe the same current state at the same time. For device types that already expose video, multiple users can view the same live video feed. For device types that expose MCP active control, many MCP sessions may observe but exactly one MCP session may control actuators.

## Scope

- Applies to all Office device types through the device adapter model.
- State observation uses the existing shadow and MCP read-only paths.
- Video observation uses the existing single AWS KVS WebRTC channel for video-capable device types.
- Control means active MCP server control only.
- REDCON management is explicitly out of scope and remains the existing Sparkplug command path and UI behavior.

## Non-goals

- No new REDCON ownership, lock, authority, or command path.
- No second KVS channel, media relay, or viewer admission-control service.
- No bandwidth or latency optimization for 2-3 viewers unless field use later shows a problem.
- No attempt to add video or MCP control to device types that do not already expose those capabilities.

## Intended behavior

- Two different signed-in users can open the same AWS device in two browsers and see the same shadow-derived device state.
- For video-capable devices, both browsers can open the same live video feed.
- For MCP-capable devices, both browsers may maintain MCP sessions for read-only state calls.
- Only the active MCP session can execute actuator tools such as cmd_vel.publish and cmd_vel.stop.
- A non-active MCP session remains observer-only until explicit takeover through control.activate with takeover true.
- On takeover, the daemon stops previous motion, switches active owner and epoch, and the former controller becomes an observer.

## Design notes

- Office should derive control availability from capabilities and the active MCP control state, not from device type names such as bot.
- Device types without MCP active control remain view-only, even when multiple users are present.
- Office should send the signed-in user identity as the MCP actor so observers can see who owns active control.
- Office should consume published MCP active-control status where available so ownership changes are visible without waiting only for periodic robot.get_state polling.
- The video worker already supports multiple peer sessions on one KVS channel; implementation should keep that topology and add only validation or observability needed for supported operation.

## Interfaces

- MCP status should document the activeControl object with sessionId, actor, transport, sinceMs, expiresAtMs, and epoch.
- UI logic should interpret activeHeldByCaller locally by comparing the active owner session with the current browser MCP session.
- Video status may add viewerCount as non-authoritative observability; viewerConnected remains compatible and is not admission control.

## Validation

- First manual validation: two browsers on the same computer, two different users, same AWS device, both observing the same state.
- Final manual validation: two browsers see the same bot video, one browser controls the bot, observer cannot control until explicit takeover.
- Automated validation should cover Office UI state, daemon active-control enforcement, and unchanged REDCON command behavior.
