# Future Work

This document records backlog items and technical debt that should not block the
current implementation track, but should be kept visible for later cleanup or
larger dependency work.

## Rig Host Credentials

The standalone rig host keeps only its IoT certificate/private key and does not
store AWS access keys.

## Cloud And Control-Only RTC Consumers

The current unit implementation uses one AWS KVS media session for browser
video and MCP control at REDCON `1`, and MQTT MCP at REDCON `2` when video is
unavailable or not ready. That path is complete for the current browser
operator workflow.

Future work may add non-browser session consumers:

- a cloud worker that connects as another MCP session and uses the existing
  `control.activate` takeover semantics
- a no-video or control-only WebRTC worker for device types where MCP should
  use WebRTC without a media track
- a distinct KVS signaling channel for a control-only WebRTC path, if a future
  device needs it
- admission, scheduling, or policy around cloud workers competing with human
  operators for the single active-control slot

Out of scope for the current unit operator path:

- a second KVS channel for the current `unit` path
- a cloud session consumer before there is a concrete product use case
- active-control protocol changes for this future work unless a real protocol
  gap is found
