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
- `board.*` is owned by the device-side board reporter (`board`) as the source of truth for board-related shadow data.
- Only `board` is allowed to define or evolve fields under `board`.
- Other components must treat `board.*` as a stable contract and must not add, rename, or repurpose fields.

## AWS IoT note

AWS IoT Thing Shadows do not enforce a custom JSON schema automatically.
Schema validation should be done by project code and/or CI checks, while AWS IoT stores the JSON document.

## Required project fields

- Terminology: `power=true` means the wakeup state, and `power=false` means the sleep state with periodic `5 s` BLE rendezvous wakeups.
- `state.desired.mcu.power` (`boolean`) requests the MCU power mode: `true` keeps the MCU in the wakeup state and BLE-connectable, `false` returns it to the sleep state with periodic low-power rendezvous wakeups.
- `state.reported.mcu.power` (`boolean`) is the gateway-confirmed MCU power mode.
- `state.reported.mcu.batteryMv` (`integer`, millivolts, measured MCU battery estimate observed from the MCU State Report over BLE advertising or GATT).
- `state.reported.mcu.ble.serviceUuid` (`uuid`) is the BLE service UUID used by gateway.
- `state.reported.mcu.ble.sleepCommandUuid` (`uuid`) is the compatibility field for the BLE power-mode control characteristic UUID.
- `state.reported.mcu.ble.stateReportUuid` (`uuid`) is the BLE read+notify characteristic UUID.
- `state.reported.mcu.ble.online` (`boolean`) is gateway-observed BLE reachability: it becomes `true` after the device has shown sustained BLE presence, and becomes `false` only after the device has not been seen for the configured presence timeout.
- `state.reported.mcu.ble.deviceId` (`string`, optional) is the last known BLE device identifier used for fast reconnect.
- `state.reported.board.online` (`boolean`) is a best-effort board-process online flag; because the board can lose power abruptly, consumers must not treat stale `true` as authoritative after a hard power cut.
- `state.reported.board.hostname` (`string`) is the board hostname or configured board name.
- `state.reported.board.model` (`string`, optional) is the detected Raspberry Pi model string.
- `state.reported.board.bootId` (`string`) is the current Linux boot identifier for the board.
- `state.reported.board.programVersion` (`string`) is the running board reporter version.
- `state.reported.board.startedAt` (`RFC3339 string`) is the board reporter process start time in UTC.
- `state.reported.board.reportedAt` (`RFC3339 string`) is the last successful board shadow publish time in UTC.
- `state.reported.board.uptimeSeconds` (`integer`) is the board uptime estimate from the local OS.
- `state.reported.board.clientId` (`string`) is the MQTT client identifier used by the board reporter.

Unknown fields are allowed for forward compatibility and must be ignored by consumers.
