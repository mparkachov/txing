# Txing Thing Shadow Model

This document defines how shadow structure is governed across the repo.

## Status

- This document describes the current Sparkplug-backed shadow model implemented in the repo.
- Sparkplug `DCMD.redcon` is the only authoritative external lifecycle intent path.
- The classic `txing` Thing Shadow remains the lifecycle reflection and restart-cache document.
- `rig` and `town` are Sparkplug identifiers only; they do not have AWS IoT thing shadows.
- The design background remains documented in `docs/sparkplug-lifecycle.md`.

## Canonical schema

- Schema file: `./txing-shadow.schema.json`
- Thing names:
  - `txing`: device shadow
- Shadow type: classic (unnamed) Thing Shadow for the txing thing only
- High-level paths:
  - `Sparkplug host -> AWS IoT MQTT -> rig (current rig runtime) -> BLE -> mcu`
  - `rig -> AWS IoT Thing Shadow (txing)`
  - `board -> AWS IoT Thing Shadow (txing.board.*)`

## Ownership decision

- `mcu.*` is owned by the `rig` runtime acting as the lifecycle service.
- Only `rig` is allowed to define or evolve fields under `mcu`.
- Other components must treat `mcu.*` as a stable contract and must not add, rename, or repurpose fields.
- Top-level direct Sparkplug metric reflections under `txing.state.reported` are owned by `rig`.
- In the current implementation that strict direct-metric set is exactly:
  - `txing.state.reported.redcon`
  - no other top-level direct metric
- `txing.state.reported.device.batteryMv` is the nested Sparkplug battery metric reflection.
- There is no `txing.state.desired` lifecycle surface.
- `board.*` remains board-owned, and top-level `video.*` is reflected into shadow by `rig` from retained MQTT video service topics.
- Only `board` is allowed to define or evolve board-owned fields, and only `rig` may evolve the reflected top-level `video.*` shadow shape.
- Other components must treat `board.*` as a stable contract and must not add, rename, or repurpose fields.

## AWS IoT note

AWS IoT Thing Shadows do not enforce a custom JSON schema automatically.
Schema validation should be done by project code and/or CI checks, while AWS IoT stores the JSON document.

Current implementation note:

- Sparkplug owns lifecycle intent.
- Shadow is a reported-only reflection document.
- `rig` derives `reported.redcon` from BLE reachability, MCU wake state, retained MCP availability, and retained video readiness.
- Direct scalar attributes under `state.reported` are a strict reflection of the current Sparkplug device metrics only.
- In the current implementation that direct-metric set is exactly `redcon`.
- `device.batteryMv`, `device.mcu.*`, and `device.board.*` remain nested operational detail.
- Stable per-device metadata lives in AWS IoT thing attributes instead:
  - `attributes.name`
  - `attributes.shortId`
  - `attributes.town`
  - `attributes.rig`
  - `attributes.bleDeviceId`
- Search/index use is narrower:
  - `attributes.name` is searchable on all txing thing types
  - `attributes.town` is searchable on `rig` and device things
  - `attributes.rig` is searchable on device things
  - `attributes.shortId` and `attributes.bleDeviceId` stay as metadata only

## Required project fields

- Terminology: `power=true` means the wakeup state, and `power=false` means the sleep state with periodic `5 s` BLE rendezvous wakeups.
- Lifecycle targets are transient in-memory rig state only; a restart requires a fresh Sparkplug command.
- `state.reported.device.mcu.power` (`boolean`) is the rig-confirmed MCU power mode.
- `state.reported.device.mcu.online` (`boolean`) is rig-observed BLE reachability: it becomes `true` after the device has shown sustained BLE presence, and becomes `false` only after the device has not been seen for the configured presence timeout.
- `state.reported.redcon` (`integer`, `1..4`) is the rig-derived readiness summary:
  - `4`: Green / `Cold Camp` / MCU sleep state or BLE unavailable
  - `3`: Yellow / `Torch-Up` / MCU wakeup state with BLE reachability, but MCP unavailable
  - `2`: Orange/Amber / `Ember Watch` / MCU wakeup state with BLE reachability and MCP availability, but retained video status not ready
  - `1`: Red / `Hot Rig` / MCU wakeup state with BLE reachability, MCP availability, and retained video status ready
- `state.reported.device.batteryMv` (`integer`, millivolts, measured MCU battery estimate observed from the MCU State Report over BLE advertising or GATT).
- `state.reported.device.board.power` (`boolean`) is a best-effort board power-state flag; because the board can lose power abruptly through the MOSFET, consumers must not treat stale `true` as authoritative after a hard power cut.
- `state.reported.device.board.wifi.online` (`boolean`) is the board-side Wi-Fi/control online flag while the board OS is up and the board control is running.
- `state.reported.device.board.wifi.ipv4` (`ipv4 string`, update payload may temporarily use `null` to delete) is the IPv4 address chosen by the OS for the board's current IPv4 default-route interface when the board control publishes.
- `state.reported.device.board.wifi.ipv6` (`ipv6 string`, update payload may temporarily use `null` to delete) is the IPv6 address chosen by the OS for the board's current IPv6 default-route interface when the board control publishes.
- Live board motion feedback and board video runtime state are no longer part of the Thing Shadow contract in Phase 3.
- Current motion state and current video runtime state are read from board MCP `robot.get_state`.
- For `reported.redcon`, rig treats retained MCP availability plus fresh retained video readiness as the final readiness inputs once BLE reachability and MCU wake state are satisfied.
- Current design intent is plain AWS WebRTC only for the live operator path.
- The current implementation does not assume WebRTC ingestion/storage, multiviewer, or `kvssink`.
- Whether a second direct operator path is needed later is explicitly deferred until future field use.

## Web admin transport note

- The browser admin SPA uses Sparkplug device traffic as the primary live REDCON read path and keeps the classic `txing` Thing Shadow as the reflected detail/debug document.
- Browser lifecycle writes no longer target shadow desired power fields.
- The browser operator control now uses a single `Connect` / `Disconnect` button gated only by primary REDCON `1`.
- The current on/off switch publishes Sparkplug `DCMD.redcon` over MQTT/WSS:
  - `on` -> `redcon=3`
  - `off` -> `redcon=4`
- The browser consumes `DBIRTH`, `DDATA`, and `DDEATH` for the selected device and falls back to `state.reported.redcon` only before the first device lifecycle packet arrives.
- `board` and `rig` continue to publish reflected operational state for `txing`; there are no separate `rig` or `town` shadows.
- Registry metadata remains out of the shadow path; `attributes.rig` and `attributes.bleDeviceId` are rig-managed.
- The browser still uses HTTPS for Cognito hosted UI, Cognito token exchange/refresh, Cognito Identity credential bootstrap, and IoT policy attachment. Only shadow document traffic moved to MQTT/WSS.
- Live board motion control remains out of band and is not part of the Thing Shadow contract.
- The remote board control API is MCP only:
  - `control.acquire_lease`
  - `control.renew_lease`
  - `control.release_lease`
  - `cmd_vel.publish`
  - `cmd_vel.stop`
  - `robot.get_state`
- `cmd_vel.publish` uses strict ROS `geometry_msgs/Twist` semantics:
  - `linear.x` is forward body velocity in `m/s`
  - `angular.z` is yaw rate in `rad/s`
  - `linear.y`, `linear.z`, `angular.x`, and `angular.y` are unsupported on the current differential-drive board and must be `0`

Unknown fields are allowed for forward compatibility and must be ignored by consumers.
