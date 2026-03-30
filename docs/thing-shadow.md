# Txing Thing Shadow Model

This document defines how shadow structure is governed across the repo.

## Canonical schema

- Schema file: `./txing-shadow.schema.json`
- Thing name: `txing`
- Shadow type: classic (unnamed) Thing Shadow
- High-level paths:
  - `AWS IoT Device Shadow -> MQTT -> gw -> BLE -> mcu`
  - `AWS IoT Device Shadow -> MQTT -> board`

## Ownership decision

- `mcu.*` is owned by the gateway (`gw`) as the source of truth for MCU-related shadow data.
- Only `gw` is allowed to define or evolve fields under `mcu`.
- Other components must treat `mcu.*` as a stable contract and must not add, rename, or repurpose fields.
- Top-level `reported.redcon` is owned by the gateway (`gw`) as a derived readiness summary computed from reported MCU and board state.
- `board.*` is owned by the device-side board control (`board`) as the source of truth for board-related shadow data.
- Only `board` is allowed to define or evolve fields under `board`.
- Other components must treat `board.*` as a stable contract and must not add, rename, or repurpose fields.

## AWS IoT note

AWS IoT Thing Shadows do not enforce a custom JSON schema automatically.
Schema validation should be done by project code and/or CI checks, while AWS IoT stores the JSON document.

## Required project fields

- Terminology: `power=true` means the wakeup state, and `power=false` means the sleep state with periodic `5 s` BLE rendezvous wakeups.
- `state.desired.mcu.power` (`boolean`, update payload may temporarily use `null` to delete) requests the MCU power mode: `true` keeps the MCU in the wakeup state and BLE-connectable, `false` returns it to the sleep state with periodic low-power rendezvous wakeups.
- `state.desired.board.power` (`boolean`, update payload may temporarily use `null` to delete) is a board-owned one-shot board power request: `false` asks the board Pi to halt locally, and the board control clears the field on clean shutdown after consuming it.
- `state.reported.mcu.power` (`boolean`) is the gateway-confirmed MCU power mode.
- `state.reported.redcon` (`integer`, `1..4`) is the gateway-derived readiness summary:
  - `4`: Green / `Cold Camp` / MCU sleep state
  - `3`: Yellow / `Torch-Up` / MCU wakeup state while the operator video path is not ready
  - `2`: Orange/Amber / `Ember Watch` / MCU wakeup state with board power, board Wi-Fi/control, and board video ready, but no active viewer
  - `1`: Red / `Hot Rig` / same as `2`, plus `reported.board.video.viewerConnected=true`
- `state.reported.mcu.batteryMv` (`integer`, millivolts, measured MCU battery estimate observed from the MCU State Report over BLE advertising or GATT).
- `state.reported.mcu.ble.serviceUuid` (`uuid`) is the BLE service UUID used by gateway.
- `state.reported.mcu.ble.sleepCommandUuid` (`uuid`) is the compatibility field for the BLE power-mode control characteristic UUID.
- `state.reported.mcu.ble.stateReportUuid` (`uuid`) is the BLE read+notify characteristic UUID.
- `state.reported.mcu.ble.online` (`boolean`) is gateway-observed BLE reachability: it becomes `true` after the device has shown sustained BLE presence, and becomes `false` only after the device has not been seen for the configured presence timeout.
- `state.reported.mcu.ble.deviceId` (`string`, optional, update payload may temporarily use `null` to delete) is the last known BLE device identifier used for fast reconnect.
- `state.reported.board.power` (`boolean`) is a best-effort board power-state flag; because the board can lose power abruptly through the MOSFET, consumers must not treat stale `true` as authoritative after a hard power cut.
- `state.reported.board.wifi.online` (`boolean`) is the board-side Wi-Fi/control online flag while the board OS is up and the board control is running.
- `state.reported.board.wifi.ipv4` (`ipv4 string`, update payload may temporarily use `null` to delete) is the IPv4 address chosen by the OS for the board's current IPv4 default-route interface when the board control publishes.
- `state.reported.board.wifi.ipv6` (`ipv6 string`, update payload may temporarily use `null` to delete) is the IPv6 address chosen by the OS for the board's current IPv6 default-route interface when the board control publishes.
- `state.reported.board.drive.leftSpeed` (`integer`, `-100..100`) is the last applied left track effort reported by `txing-board` as a provisional signed percent scale.
- `state.reported.board.drive.rightSpeed` (`integer`, `-100..100`) is the last applied right track effort reported by `txing-board` as a provisional signed percent scale.
- `state.reported.board.video.ready` (`boolean`) indicates whether the phase-1 plain AWS WebRTC live path is ready for operator use.
- `state.reported.board.video.status` (`"starting" | "ready" | "error"`) is the coarse runtime state of the board video sender path.
- `state.reported.board.video.transport` (`"aws-webrtc"`) identifies the live-video transport. Phase 1 uses `aws-webrtc` as the only live operator path, specifically as a plain KVS WebRTC signaling session.
- `state.reported.board.video.session.viewerUrl` (`string`, update payload may temporarily use `null` to delete) is the operator-facing browser entry URL when a browser route exists for the live video session.
- `state.reported.board.video.session.channelName` (`string`, update payload may temporarily use `null` to delete) is the KVS WebRTC signaling channel name for browser or native clients.
- `state.reported.board.video.codec.video` (`"h264"` or `null`) is the currently configured board video codec.
- `state.reported.board.video.viewerConnected` (`boolean`) is the best-effort operator-viewer presence flag for the live path.
- `state.reported.board.video.lastError` (`string` or `null`) is the last coarse board-side video error surfaced by `txing-board` or its supervised sender path.
- For `reported.redcon`, the gateway treats `reported.board.power`, `reported.board.wifi.online`, `reported.board.video.ready`, and `reported.board.video.viewerConnected` as the shared board posture inputs.
- Phase-1 design intent is now plain AWS WebRTC only for the live operator path.
- Phase 1 does not assume WebRTC ingestion/storage, multiviewer, or `kvssink`.
- Whether a second direct operator path is needed later is explicitly deferred until field tests.

## Web admin transport note

- The browser admin SPA consumes the classic `txing` Thing Shadow over AWS IoT MQTT/WSS.
- `board` and `gw` continue to publish shadow state exactly as before; only the browser shadow transport changed from HTTP polling to push-driven MQTT shadow updates.
- The browser still uses HTTPS for Cognito hosted UI, Cognito token exchange/refresh, Cognito Identity credential bootstrap, and IoT policy attachment. Only shadow document traffic moved to MQTT/WSS.
- Live board motion control remains out of band and is not part of the Thing Shadow contract. The current browser-to-board control topic is `txing/board/cmd_vel`, carrying raw JSON shaped like ROS `geometry_msgs/Twist`.
- `txing/board/cmd_vel` is a strict semantic contract, not only a ROS-shaped JSON payload:
  - `linear.x` is forward body velocity in `m/s`
  - `angular.z` is yaw rate in `rad/s`
  - `linear.y`, `linear.z`, `angular.x`, and `angular.y` are unsupported on the current differential-drive board and must be `0`
- The browser teleop implementation is only one producer of this contract. AI clients and any future producers must publish the same strict `Twist` semantics and must not rely on browser-specific key-step behavior.

Unknown fields are allowed for forward compatibility and must be ignored by consumers.
