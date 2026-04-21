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
  - `txing.state.reported.batteryMv`
- Top-level `txing.state.desired.redcon` is owned by `rig` as the reflected cache of the latest unresolved Sparkplug lifecycle command.
- `txing.state.desired.board.power` remains an internal rig-to-board graceful-halt actuator only. It is not a public lifecycle API.
- `board.*` remains board-owned, and top-level `video.*` is reflected into shadow by `rig` from retained MQTT video service topics.
- Only `board` is allowed to define or evolve board-owned fields, and only `rig` may evolve the reflected top-level `video.*` shadow shape.
- Other components must treat `board.*` as a stable contract and must not add, rename, or repurpose fields.

## AWS IoT note

AWS IoT Thing Shadows do not enforce a custom JSON schema automatically.
Schema validation should be done by project code and/or CI checks, while AWS IoT stores the JSON document.

Current implementation note:

- Sparkplug owns lifecycle intent.
- Shadow is reflection and restart cache.
- `rig` derives `reported.redcon` from BLE reachability, MCU wake state, retained MCP availability, and retained video readiness.
- Direct scalar attributes under `state.reported` are a strict reflection of the current Sparkplug device metrics only.
- In the current implementation that direct-metric set is exactly `redcon` and `batteryMv`.
- `mcu.*` and `board.*` remain additional operational detail and must not be used as alternate Sparkplug metric locations.
- Stable per-device metadata lives in AWS IoT thing attributes instead:
  - `attributes.rig`
  - `attributes.bleDeviceId`

## Required project fields

- Terminology: `power=true` means the wakeup state, and `power=false` means the sleep state with periodic `5 s` BLE rendezvous wakeups.
- `state.desired.redcon` (`integer | null`, `1..4`) reflects the latest unresolved Sparkplug lifecycle target for `txing`. `rig` writes it when a valid `DCMD.redcon` arrives and clears it after convergence or `DDEATH`.
- `state.desired.board.power` (`boolean | null`, update payload may temporarily use `null` to delete) is an internal rig-to-board one-shot graceful-halt request: `false` asks the board Pi to halt locally before `rig` sends the MCU sleep command for `REDCON 4`.
- `state.reported.mcu.power` (`boolean`) is the rig-confirmed MCU power mode.
- `state.reported.mcu.online` (`boolean`) is rig-observed BLE reachability: it becomes `true` after the device has shown sustained BLE presence, and becomes `false` only after the device has not been seen for the configured presence timeout.
- `state.reported.redcon` (`integer`, `1..4`) is the rig-derived readiness summary:
  - `4`: Green / `Cold Camp` / MCU sleep state or BLE unavailable
  - `3`: Yellow / `Torch-Up` / MCU wakeup state with BLE reachability, but MCP unavailable
  - `2`: Orange/Amber / `Ember Watch` / MCU wakeup state with BLE reachability and MCP availability, but retained video status not ready
  - `1`: Red / `Hot Rig` / MCU wakeup state with BLE reachability, MCP availability, and retained video status ready
- `state.reported.batteryMv` (`integer`, millivolts, measured MCU battery estimate observed from the MCU State Report over BLE advertising or GATT).
- `state.reported.board.power` (`boolean`) is a best-effort board power-state flag; because the board can lose power abruptly through the MOSFET, consumers must not treat stale `true` as authoritative after a hard power cut.
- `state.reported.board.wifi.online` (`boolean`) is the board-side Wi-Fi/control online flag while the board OS is up and the board control is running.
- `state.reported.board.wifi.ipv4` (`ipv4 string`, update payload may temporarily use `null` to delete) is the IPv4 address chosen by the OS for the board's current IPv4 default-route interface when the board control publishes.
- `state.reported.board.wifi.ipv6` (`ipv6 string`, update payload may temporarily use `null` to delete) is the IPv6 address chosen by the OS for the board's current IPv6 default-route interface when the board control publishes.
- `state.reported.board.drive.leftSpeed` (`integer`, `-100..100`) is the last applied left track effort reported by `txing-board` as a provisional signed percent scale.
- `state.reported.board.drive.rightSpeed` (`integer`, `-100..100`) is the last applied right track effort reported by `txing-board` as a provisional signed percent scale.
- `state.reported.video.serviceId` (`"video"`) identifies the rig-reflected board video service record.
- `state.reported.video.serverInfo.name` / `version` (`string`) mirror the retained video descriptor server info fields.
- `state.reported.video.available` (`boolean`) indicates whether the board video service is available according to the retained MQTT status feed.
- `state.reported.video.ready` (`boolean`) indicates whether the current plain AWS WebRTC live path is ready for operator use.
- `state.reported.video.status` (`"starting" | "ready" | "error" | "unavailable"`) is the coarse runtime state of the retained board video service feed.
- `state.reported.video.transport` (`"aws-webrtc"`) identifies the live-video transport. The current implementation uses `aws-webrtc` as the only live operator path, specifically as a plain KVS WebRTC signaling session.
- `state.reported.video.codec.video` (`"h264"` or `null`) is the currently configured board video codec.
- `state.reported.video.viewerConnected` (`boolean`) is the best-effort operator-viewer presence flag for the live path. It is informational and does not participate in `reported.redcon`.
- `state.reported.video.lastError` (`string` or `null`) is the last coarse board-side video error surfaced by `txing-board` or its supervised sender path.
- `state.reported.video.updatedAtMs` (`integer | null`) is the latest retained MQTT status timestamp reflected by `rig`; readiness becomes stale when that retained status ages past the rig freshness threshold.
- `state.reported.video.topicRoot`, `descriptorTopic`, `statusTopic`, `channelName`, `region`, and `serverVersion` are retained-service metadata reflected by `rig` from `txings/<device_id>/video/descriptor`.
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
- Live board motion control remains out of band and is not part of the Thing Shadow contract. The current browser-to-board control topic is `txing/board/cmd_vel`, carrying raw JSON shaped like ROS `geometry_msgs/Twist`.
- `txing/board/cmd_vel` is a strict semantic contract, not only a ROS-shaped JSON payload:
  - `linear.x` is forward body velocity in `m/s`
  - `angular.z` is yaw rate in `rad/s`
  - `linear.y`, `linear.z`, `angular.x`, and `angular.y` are unsupported on the current differential-drive board and must be `0`
- The browser teleop implementation is only one producer of this contract. AI clients and any future producers must publish the same strict `Twist` semantics and must not rely on browser-specific key-step behavior.

Unknown fields are allowed for forward compatibility and must be ignored by consumers.
