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

## 3. Rendezvous Model

The BLE link is no longer persistent.

Firmware behavior:
- stay in low-power system-on idle between rendezvous intervals
- wake itself from RTC every `5 s`
- advertise for `1 s`
- accept a short connection
- process a one-byte wake command
- return to sleep after disconnect or timeout

Gateway behavior:
- keep a registry for the known device identity
- keep scanning while disconnected
- treat disconnects as expected
- reconnect only during the periodic advertising window
- send the wake command immediately after connection
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
- `state.desired.mcu.power=true` means "deliver a wake command on the next BLE rendezvous".
- `state.desired.mcu.power=false` means "clear the wake latch / no wake request pending".
- `state.reported.mcu.power=true` means "gateway delivered a wake command successfully".
- `state.reported.mcu.power=false` means "no delivered wake command is currently latched".
- `state.reported.mcu.batteryMv` is the latest battery reading observed over BLE.
- `state.reported.mcu.ble.online` is `true` only while the short BLE session is connected.
- `state.reported.mcu.ble.deviceId` is the last known BLE identity used for fast reconnect.

Compatibility note:
- The shadow field name `sleepCommandUuid` is retained for compatibility.
- In v1.0 it identifies the wake-command characteristic, not a persistent sleep-mode toggle.

## 5. BLE GATT Contract

UUIDs:
- Service `TXING Control`: `f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100`
- Wake Command characteristic (compatibility field `sleepCommandUuid`): `f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100`
- State Report characteristic: `f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100`

Payloads:
- Wake Command (1 byte, write with response):
  - `0x01` -> trigger wake action
  - `0x00` -> accepted as a legacy wake alias
- State Report (3 bytes, read + notify):
  - byte 0: status
  - bytes 1..2: `battery_mv` as little-endian `u16`

State Report status values:
- `0x00` -> idle/listening
- `0x01` -> wake command acknowledged during the current connection

Notification behavior:
- Device updates State Report on connection establishment.
- Device updates State Report again after processing a wake command.
- Gateway may use either reads or notifications; current implementation uses reads.

## 6. Firmware State Machine

States:
- `Sleep`
  - LED off.
  - RTC timer armed for the next rendezvous interval.
  - Transition to `Wake` when the timer expires.
- `Wake`
  - Refresh battery measurement.
  - Reset State Report status to `idle`.
  - Transition immediately to `Advertising`.
- `Advertising`
  - Start connectable advertising with a bounded timeout.
  - Transition to `Connected` if the gateway connects.
  - Transition to `ReturnToSleep` if the advertising window expires.
- `Connected`
  - Publish State Report to the client.
  - Start a bounded command window.
  - Transition to `CommandProcessing` when a valid wake command is written.
  - Transition to `ReturnToSleep` on disconnect or command timeout.
- `CommandProcessing`
  - Trigger the wake action.
  - Update State Report status to `wake acknowledged`.
  - Transition back to `Connected` until the link closes.
- `ReturnToSleep`
  - Clear transient command status.
  - Transition to `Sleep`.

## 7. Gateway State Machine

States:
- `Idle`
  - No BLE action pending.
  - Scanner remains armed in the background.
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
  - If no wake is pending, disconnect and return to `Scanning`.
- `CommandPending`
  - `desired.mcu.power=true` and `reported.mcu.power=false`.
  - Write the wake command.
- `CommandSent`
  - Poll State Report until acknowledgement or timeout.
  - On acknowledgement, set `reported.mcu.power=true`, clear desired, then disconnect.
- `Disconnect`
  - Publish `ble.online=false`.
  - Restart scanner.
- `WaitForNextAdvertisement`
  - The advertising window was missed or connect/ack failed.
  - Return to `Scanning`.

Normal-disconnect rule:
- Disconnects after a short session are expected behavior and must not reset the known-device registry.

## 8. Timing Defaults

Firmware defaults:
- sleep interval: `5 s`
- advertising window: `1 s`
- advertising interval: `150 ms`
- connected command window: `1 s`

Gateway defaults:
- scan timeout before logging a missed window: `12 s`
- connect timeout: `5 s`
- wake acknowledgement timeout: `1 s`
- acknowledgement poll interval: `100 ms`
- advertisement freshness threshold: `750 ms`
- scan mode: `active`

All of the above are tunable constants or CLI-configurable parameters.

## 9. Acceptance Criteria

- From `reported.mcu.power=false`, setting `desired.mcu.power=true` eventually results in:
  - a BLE connection during a rendezvous window
  - a successful wake command write
  - a State Report acknowledgement
  - `state.reported.mcu.power=true`
- Setting `desired.mcu.power=false` clears the wake latch without requiring a BLE reconnect.
- `state.reported.mcu.batteryMv` is refreshed whenever the gateway completes a BLE rendezvous.
- `state.reported.mcu.ble.*` remains present and valid.
- `state.reported.mcu.ble.online` flips `false -> true -> false` around each short BLE session.

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
