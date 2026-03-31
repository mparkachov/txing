# Txing Gateway Contract (Shadow + Sparkplug + BLE) v1.1

This document is the integration contract for the gateway team only.
Build, flash, and local developer commands live in the subproject READMEs.

Status note:

- This document describes the current implemented phase-1 `gw` runtime contract.
- `gw` now acts as the phase-1 `rig` lifecycle service in the same process.
- Sparkplug `DCMD.redcon` is the authoritative lifecycle command path.
- The `txing` Thing Shadow remains the reflected operational document and restart cache.
- For the broader design context, see `docs/sparkplug-phase1-design.md`.

## 1. Scope

Contract between:
- Txing firmware (`mcu/`, BLE peripheral on nRF52840)
- Txing gateway (`gw/`, BLE central on Raspberry Pi 5 and phase-1 `rig` lifecycle runtime)
- AWS IoT classic Thing Shadow for thing name `txing`
- AWS IoT MQTT Sparkplug namespace `spBv1.0`

Authoritative shadow schema:
- `./txing-shadow.schema.json`

High-level architecture:
- Sparkplug host -> AWS IoT MQTT -> gw -> BLE -> mcu
- gw -> AWS IoT Thing Shadow reflection/cache

## 2. Ownership

- `gw` is the source of truth for the `mcu.*` shadow subtree.
- `gw` is also the source of truth for top-level `reported.redcon`, derived from reported MCU and board posture.
- `gw` is the only component that accepts lifecycle intent from Sparkplug and reflects unresolved intent into `state.desired.redcon`.
- `state.desired.board.power` remains an internal rig-to-board actuator only.
- `state.desired.mcu.power` is deprecated and ignored by runtime logic.
- Only `gw` may define or evolve the `mcu.*` contract.
- `mcu` exposes BLE behavior; `gw` translates that behavior into shadow state.

## 3. Hybrid BLE Model

Terminology:
- `power=true` means the MCU is in the wakeup state.
- `power=false` means the MCU is in the sleep state.
- The firmware also has an internal `Wake` step inside the sleep-state rendezvous cycle. That internal state is not the same thing as the external wakeup state.

The BLE link is intended to be persistent only while the MCU is in the wakeup state.

Firmware behavior:
- `power=false`: stay in RTC-driven low-power system-on idle between rendezvous intervals, wake from RTC every `5 s`, refresh the State Report, restart BLE advertising for a short bounded window, accept a short connection if needed, then return to low-power idle
- `power=true`: stay in the wakeup state, continue advertising when disconnected, and keep the BLE link available for a live session

Gateway behavior:
- keep a registry for the known device identity
- keep scanning while disconnected
- while the MCU is in the sleep state, observe the periodic advertising windows to maintain BLE presence and reconnect during a rendezvous window only when a BLE session is needed
- while the MCU is in the wakeup state, keep a live BLE session available when possible
- treat disconnects during sleep-state transitions as expected behavior
- avoid full rediscovery once UUIDs and device identity are known

Power note:
- The implementation uses RTC-driven system-on low-power idle instead of full System OFF.
- Reason: the device must self-wake periodically from a low-frequency timer; that is the lowest practical mode for this behavior.
- Sleep-mode low-power measures keep the external flash in deep power-down, drive the Sense-board IMU and microphone power-enable GPIOs low, and park the related unused pins.
- Battery-sense divider gating is intentionally not used: Seeed documents that driving `P0.14` high can expose `P0.31` to battery voltage during charging.
- The board Pi power rail is switched by an external MOSFET driven from nRF pin `D0` / `P0.02`.
- Firmware drives that GPIO high in the wakeup state and low in the sleep state.

## 4. Shadow Contract

Thing name: `txing`
Shadow type: classic (unnamed) Thing Shadow (`$aws/things/txing/shadow/*`)

```json
{
  "state": {
    "desired": {
      "redcon": 3,
      "board": {
        "power": null
      }
    },
    "reported": {
      "redcon": 4,
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
- `state.desired.redcon` is the reflected cache of the latest unresolved Sparkplug `DCMD.redcon` command.
- `state.desired.board.power=false` is an internal-only graceful-halt request written by `gw` while converging `redcon=4`.
- `state.desired.mcu.power` is deprecated compatibility state and must be ignored by phase-1 runtime behavior.
- `state.reported.redcon` is the derived readiness summary:
  - `4` -> Green / `Cold Camp` -> `reported.mcu.power=false`
  - `3` -> Yellow / `Torch-Up` -> `reported.mcu.power=true` while the operator video path is not ready yet
  - `2` -> Orange/Amber / `Ember Watch` -> `reported.mcu.power=true`, `reported.board.power=true`, `reported.board.wifi.online=true`, `reported.board.video.ready=true`, and `reported.board.video.viewerConnected=false`
  - `1` -> Red / `Hot Rig` -> same as `2`, plus `reported.board.video.viewerConnected=true`
- `state.reported.mcu.power=true` means "MCU is in the wakeup state".
- `state.reported.mcu.power=false` means "MCU is in the sleep state with periodic BLE rendezvous wakeups".
- `state.reported.mcu.batteryMv` is the latest battery reading observed over BLE, sourced from the MCU state report carried over either advertising manufacturer data or the GATT State Report characteristic.
- `state.reported.mcu.ble.online` is `true` only after the MCU has shown sustained BLE reachability, either by staying connected or by advertising regularly for the configured recovery window.
- `state.reported.mcu.ble.deviceId` is the last known BLE identity used for fast reconnect.
- `gw` reads `state.reported.board.power`, `state.reported.board.wifi.online`, `state.reported.board.video.ready`, and `state.reported.board.video.viewerConnected` from the shared shadow as the board posture inputs for `reported.redcon`.
- `gw` emits `DBIRTH` when BLE reachability reaches the same sustained-online condition that drives `reported.mcu.ble.online=true`.
- `gw` emits `DDEATH` when BLE reachability times out, forces `reported.redcon=4`, and clears `desired.redcon` plus internal `desired.board.power` best-effort.

Compatibility note:
- The shadow field name `sleepCommandUuid` is retained for compatibility.
- In v1.0 it identifies the MCU power-mode control characteristic.

## 4A. Sparkplug Contract

Namespace and identity:
- Namespace: `spBv1.0`
- Group id: `town`
- Edge node id: `rig`
- Device id: configured txing thing name

Phase-1 metrics:
- Node metric: `rig.redcon`
- Device metrics: `redcon`, `batteryMv`
- Writable device command metric: `redcon`

Phase-1 topics:
- `NBIRTH` and `NDATA` for `rig`
- `DBIRTH`, `DDATA`, and `DDEATH` for `txing`
- `DCMD` for txing lifecycle commands

Command semantics:
- Only literal integer `1..4` values for `DCMD.redcon` are accepted.
- `redcon=4` converges toward the MCU sleep state.
- `redcon=1`, `2`, or `3` only require wakeup-state BLE actuation if the MCU is asleep.

## 5. BLE GATT Contract

UUIDs:
- Service `TXING Control`: `f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100`
- Power Command characteristic (compatibility field `sleepCommandUuid`): `f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100`
- State Report characteristic: `f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100`

Payloads:
- Advertisement manufacturer data:
  - bytes 0..1: marker `TX`
  - bytes 2..4: the same 3-byte State Report payload used by GATT
- Power Command (1 byte, write with response):
  - `0x00` -> wakeup state / `power=true`
  - `0x01` -> sleep state / `power=false`
- State Report (3 bytes, read + notify):
  - byte 0: sleep flag
  - bytes 1..2: `battery_mv` as little-endian `u16`

State Report sleep-flag values:
- `0x00` -> wakeup state / `power=true`
- `0x01` -> sleep state / `power=false`

Notification behavior:
- Device refreshes battery and rebuilds the State Report before each sleep-state advertisement window.
- Device refreshes battery before wakeup-state advertising starts and periodically while a BLE connection is held open.
- Device updates State Report on connection establishment and again after processing a power-mode command.
- Gateway consumes the same State Report payload from either advertising manufacturer data or the GATT State Report characteristic.

## 6. Firmware State Machine

External contract note:
- `power=false` corresponds to the sleep state.
- `power=true` corresponds to the wakeup state.
- The internal `Wake` state below is the short rendezvous step that occurs while the external state is still `power=false`.

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
  - In the sleep state, start connectable advertising with a bounded timeout.
  - In the wakeup state, advertise continuously until the gateway connects.
  - Transition to `Connected` if the gateway connects.
  - In the sleep state, transition to `ReturnToSleep` if the advertising window expires.
- `Connected`
  - Publish State Report to the client.
  - Refresh battery periodically while connected.
  - Start the bounded command window.
  - Transition to `CommandProcessing` when a valid power-mode command is written.
  - Transition to `ReturnToSleep` on disconnect or command timeout while in the sleep state.
  - Transition back to `Advertising` on disconnect while in the wakeup state.
- `CommandProcessing`
  - Apply the requested power mode.
  - Drive the board-power MOSFET high only on `sleep state -> wakeup state`.
  - Drive the board-power MOSFET low on `wakeup state -> sleep state` before returning to rendezvous idle.
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
  - `desired.redcon` is present and current `reported.redcon` has not converged yet.
  - For `redcon=4`, request internal `desired.board.power=false` first if the board is still up.
  - For `redcon=1..3`, wake the MCU only if `reported.mcu.power=false`.
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
- sleep-state rendezvous interval: `5 s`
- advertising window: `1 s`
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

- From `reported.redcon=4`, sending `DCMD.redcon=3` eventually results in:
  - a BLE connection during a rendezvous window
  - a successful wakeup-state command write
  - a State Report confirmation
  - `state.reported.mcu.power=true`
  - `state.desired.redcon` cleared once `reported.redcon <= 3`
- From `reported.mcu.power=true`, sending `DCMD.redcon=4` eventually results in:
  - if the board is still up, `state.desired.board.power=false` first
  - board-offline confirmation or continued retry if the board does not go offline yet
  - a successful sleep-state command write
  - `state.reported.mcu.power=false`
  - `state.reported.redcon=4`
  - `state.desired.redcon` cleared on convergence
  - the MCU returning to the sleep state with periodic rendezvous wakeups
- `state.reported.mcu.batteryMv` is refreshed whenever the gateway observes a changed battery value from the MCU State Report, whether that report arrives in advertising manufacturer data or over GATT.
- `state.reported.mcu.ble.*` remains present and valid.
- `state.reported.mcu.ble.online` becomes `true` again after the gateway observes sustained BLE presence for the configured recovery window.
- `state.reported.mcu.ble.online` remains `true` while the device is connected or continues advertising within the configured presence timeout.
- `state.reported.mcu.ble.online` becomes `false` only after the gateway has not observed the device for longer than the presence timeout.
- `DBIRTH` is emitted when `state.reported.mcu.ble.online` becomes `true`.
- `DDEATH` is emitted when `state.reported.mcu.ble.online` becomes `false`.

## 10. Test Plan

- Sleep-state advertisement presence:
  - Leave the MCU in the sleep state and verify that the gateway observes the repeated `5 s` advertising windows without requiring UUID rediscovery or a persistent BLE session.
- Sending wake command successfully:
  - Publish `DCMD.redcon=3` and verify wakeup-state acknowledgement plus `reported.mcu.power=true`.
- Behavior when no command is pending:
  - Observe multiple sleep-state rendezvous cycles and verify the MCU returns to low-power idle without a BLE session if the gateway does not need one.
- Behavior when the advertisement window is missed:
  - Stop the gateway temporarily so one or more windows are missed, then restart it and verify the next window succeeds.
- Repeated sleep/wakeup-state transitions:
  - Toggle `DCMD.redcon` through several `4 -> 3 -> 4` cycles and verify the registry, battery updates, board-shutdown handling, and disconnect handling remain stable.
