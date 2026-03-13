# Txing Gateway Contract (Shadow + BLE) v1.0

This document is the integration contract for the gateway team only.
Build, flash, and local developer commands live in the subproject READMEs.

## 1. Scope

Contract between:
- Txing firmware (`mcu/`, BLE peripheral on nRF52840)
- Txing gateway (`gw/`, BLE central on Raspberry Pi 5)
- AWS IoT classic Thing Shadow for thing name `txing`

Authoritative shadow schema:
- `./txing-shadow.schema.json`

High-level architecture:
- AWS IoT Device Shadow -> MQTT -> gw -> BLE -> mcu

## 2. Ownership

- `gw` is the source of truth for the `mcu.*` shadow subtree.
- Only `gw` may define or evolve the `mcu.*` contract.
- `mcu` exposes BLE behavior; `gw` translates that behavior into shadow state.

## 3. Hybrid BLE Model

The BLE link is persistent only while the MCU is in awake mode.

Firmware behavior:
- `power=false`: stay in low-power system-on idle between rendezvous intervals, wake from RTC every `5 s`, advertise briefly, accept a short connection, then return to sleep
- `power=true`: stay awake, continue advertising when disconnected, and keep the BLE link available for a live session

Gateway behavior:
- keep a registry for the known device identity
- keep scanning while disconnected
- reconnect during the periodic advertising window while the MCU is sleeping
- keep a live BLE session while the MCU is awake
- treat disconnects during sleep transitions as expected behavior
- avoid full rediscovery once UUIDs and device identity are known

Power note:
- The implementation uses RTC-driven system-on low-power idle instead of full System OFF.
- Reason: the device must self-wake periodically from a low-frequency timer; that is the lowest practical mode for this behavior.
- The board-specific wake GPIO mapping is still a hardware integration detail; firmware isolates it behind a single wake-action hook.

## 4. Shadow Contract

Thing name: `txing`
Shadow type: classic (unnamed) Thing Shadow (`$aws/things/txing/shadow/*`)

```json
{
  "state": {
    "desired": {
      "mcu": {
        "power": true
      }
    },
    "reported": {
      "mcu": {
        "power": false,
        "batteryMv": 3750,
        "ble": {
          "serviceUuid": "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100",
          "sleepCommandUuid": "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100",
          "stateReportUuid": "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100",
          "online": false,
          "deviceId": "AA:BB:CC:DD:EE:FF"
        }
      }
    }
  }
}
```

Field semantics:
- `state.desired.mcu.power=true` means "request MCU awake mode and keep BLE available".
- `state.desired.mcu.power=false` means "request MCU sleep mode with periodic BLE rendezvous".
- `state.reported.mcu.power=true` means "MCU is awake".
- `state.reported.mcu.power=false` means "MCU is in periodic low-power rendezvous mode".
- `state.reported.mcu.batteryMv` is the latest battery reading observed over BLE.
- `state.reported.mcu.ble.online` is `true` only after the MCU has shown sustained BLE reachability, either by staying connected or by advertising regularly for the configured recovery window.
- `state.reported.mcu.ble.deviceId` is the last known BLE identity used for fast reconnect.

Compatibility note:
- The shadow field name `sleepCommandUuid` is retained for compatibility.
- In v1.0 it identifies the MCU power-mode control characteristic.

## 5. BLE GATT Contract

UUIDs:
- Service `TXING Control`: `f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100`
- Power Command characteristic (compatibility field `sleepCommandUuid`): `f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100`
- State Report characteristic: `f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100`

Payloads:
- Power Command (1 byte, write with response):
  - `0x00` -> awake mode / `power=true`
  - `0x01` -> sleep mode / `power=false`
- State Report (3 bytes, read + notify):
  - byte 0: sleep flag
  - bytes 1..2: `battery_mv` as little-endian `u16`

State Report sleep-flag values:
- `0x00` -> awake mode / `power=true`
- `0x01` -> sleep mode / `power=false`

Notification behavior:
- Device updates State Report on connection establishment.
- Device updates State Report again after processing a power-mode command.
- Gateway may use either reads or notifications; current implementation uses reads.

## 6. Firmware State Machine

States:
- `Sleep`
  - LED off.
  - RTC timer armed for the next rendezvous interval.
  - Transition to `Wake` when the timer expires.
- `Wake`
  - Refresh battery measurement.
  - Publish the current sleep-state report.
  - Transition immediately to `Advertising`.
- `Advertising`
  - In sleep mode, start connectable advertising with a bounded timeout.
  - In awake mode, advertise continuously until the gateway connects.
  - Transition to `Connected` if the gateway connects.
  - In sleep mode, transition to `ReturnToSleep` if the advertising window expires.
- `Connected`
  - Publish State Report to the client.
  - Start the bounded command window.
  - Transition to `CommandProcessing` when a valid power-mode command is written.
  - Transition to `ReturnToSleep` on disconnect or command timeout while in sleep mode.
  - Transition back to `Advertising` on disconnect while in awake mode.
- `CommandProcessing`
  - Apply the requested power mode.
  - Trigger the external wake action only on `sleep -> awake`.
  - Update State Report with the new sleep flag and battery reading.
  - Transition back to `Connected` until the link closes or the mode changes.
- `ReturnToSleep`
  - Stop advertising.
  - Re-arm the RTC rendezvous timer.
  - Transition to `Sleep`.

## 7. Gateway State Machine

States:
- `Idle`
  - No BLE power transition is pending.
  - Scanner remains armed in the background.
  - `ble.online` remains `true` while the device is still being observed over BLE.
  - If `ble.online` is `false`, the gateway requires the configured recovery window of regular advertisements before setting it back to `true`.
- `Scanning`
  - Wait for either a matching advertisement or a shadow update.
  - Matching priority: known `deviceId`, then service UUID, then name/manufacturer fallback.
- `DeviceDetected`
  - A fresh advertisement from the known device is available.
  - Transition immediately to `Connecting`.
- `Connecting`
  - Stop scanning.
  - Establish a short BLE session.
  - Validate or rediscover UUIDs if needed.
- `Connected`
  - Read State Report.
  - Update battery cache.
  - If `power=false` is already confirmed and no change is pending, disconnect and return to `Idle`.
- `CommandPending`
  - `desired.mcu.power != reported.mcu.power`.
  - Write the requested power-mode command.
- `CommandSent`
  - Poll State Report until the requested power mode is confirmed or timeout expires.
- `Disconnect`
  - Restart scanner.
  - Do not force `ble.online=false`; allow recent advertising to keep the device online until the presence timeout expires.
- `WaitForNextAdvertisement`
  - The advertising window was missed or connect/ack failed.
  - Return to `Scanning`.

Normal-disconnect rule:
- Disconnects after a short session are expected behavior and must not reset the known-device registry.

## 8. Timing Defaults

Firmware defaults:
- sleep interval: `5 s`
- advertising window: `2 s`
- advertising interval: `100 ms`
- connected command window: `15 s`

Gateway defaults:
- scan timeout before logging a missed window: `12 s`
- connect timeout: `10 s`
- power confirmation timeout: `2 s`
- acknowledgement poll interval: `100 ms`
- advertisement freshness threshold: `750 ms`
- BLE online presence timeout: `30 s`
- BLE online recovery window: `30 s`
- maximum gap between advertisements during recovery: `12 s`
- scan mode: `active`

All of the above are tunable constants or CLI-configurable parameters.

## 9. Acceptance Criteria

- From `reported.mcu.power=false`, setting `desired.mcu.power=true` eventually results in:
  - a BLE connection during a rendezvous window
  - a successful awake-mode command write
  - a State Report confirmation
  - `state.reported.mcu.power=true`
- From `reported.mcu.power=true`, setting `desired.mcu.power=false` eventually results in:
  - a successful sleep-mode command write
  - `state.reported.mcu.power=false`
  - the MCU returning to periodic rendezvous mode
- `state.reported.mcu.batteryMv` is refreshed whenever the gateway completes a BLE rendezvous.
- `state.reported.mcu.ble.*` remains present and valid.
- `state.reported.mcu.ble.online` becomes `true` again after the gateway observes sustained BLE presence for the configured recovery window.
- `state.reported.mcu.ble.online` remains `true` while the device is connected or continues advertising within the configured presence timeout.
- `state.reported.mcu.ble.online` becomes `false` only after the gateway has not observed the device for longer than the presence timeout.

## 10. Test Plan

- Reconnect after periodic wake:
  - Leave the MCU sleeping and verify that the gateway reconnects on the next advertising window without UUID rediscovery.
- Sending wake command successfully:
  - Set `desired.mcu.power=true` and verify wake acknowledgement plus `reported.mcu.power=true`.
- Behavior when no command is pending:
  - Observe multiple sleep/advertise cycles and verify the MCU returns to sleep without a BLE session if the gateway does not connect.
- Behavior when the advertisement window is missed:
  - Stop the gateway temporarily so one or more windows are missed, then restart it and verify the next window succeeds.
- Repeated sleep/wake cycles:
  - Toggle `desired.mcu.power` through several `false -> true -> false` cycles and verify the registry, battery updates, and disconnect handling remain stable.
