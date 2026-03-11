# Txing Thing Shadow Model

This document defines how shadow structure is governed across the repo.

## Canonical schema

- Schema file: `./txing-shadow.schema.json`
- Thing name: `txing`
- Shadow type: classic (unnamed) Thing Shadow
- High-level path: `AWS IoT Device Shadow -> MQTT -> gw -> BLE -> mcu`

## Ownership decision

- `mcu.*` is owned by the gateway (`gw`) as the source of truth for MCU-related shadow data.
- Only `gw` is allowed to define or evolve fields under `mcu`.
- Other components must treat `mcu.*` as a stable contract and must not add, rename, or repurpose fields.

## AWS IoT note

AWS IoT Thing Shadows do not enforce a custom JSON schema automatically.
Schema validation should be done by project code and/or CI checks, while AWS IoT stores the JSON document.

## Required project fields

- `state.desired.mcu.power` (`boolean`) requests MCU power state.
- `state.reported.mcu.power` (`boolean`) is the gateway-confirmed MCU power state.
- `state.reported.mcu.batteryPercent` (`integer`, `0..100`, estimated from measured battery voltage).
- `state.reported.mcu.batteryVolt` (`number`, volts, measured MCU battery estimate).
- `state.reported.mcu.ble.serviceUuid` (`uuid`) is the BLE service UUID used by gateway.
- `state.reported.mcu.ble.sleepCommandUuid` (`uuid`) is the BLE write characteristic UUID.
- `state.reported.mcu.ble.stateReportUuid` (`uuid`) is the BLE read+notify characteristic UUID.
- `state.reported.mcu.ble.online` (`boolean`) is gateway-observed BLE link state (`true` while connected).
- `state.reported.mcu.ble.deviceId` (`string`, optional) is the last known BLE device identifier used for fast reconnect.

Unknown fields are allowed for forward compatibility and must be ignored by consumers.
