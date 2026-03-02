# Txing Gateway Contract (Shadow + BLE) v0.1

This document is the integration contract for the gateway team only.
Build, flash, and local developer commands are intentionally out of scope and live in `README.md`.

## 1. Scope

Contract between:
- Txing firmware (BLE peripheral)
- BLE gateway service (Greengrass-side component)
- AWS IoT Thing Shadow for thing name `txing`

## 2. Device State Exposed to Gateway

```rust
struct DeviceState {
    battery_pct: u8, // 0..=100, currently fixed to 50
    sleep: bool,
}
```

State semantics:
- `sleep=true`: low-power periodic listen mode
- `sleep=false`: active/awake mode
- On reset/power-cycle, device starts with `sleep=true`, `battery_pct=50`

## 3. Shadow Contract

Thing name: `txing`

```json
{
  "state": {
    "desired": {
      "sleep": false
    },
    "reported": {
      "sleep": true,
      "battery_pct": 50,
      "connected": false,
      "protocol_ver": 1
    }
  }
}
```

Rules:
- Command input is `state.desired.sleep`
- Confirmed device state is `state.reported.sleep`
- Battery value is `state.reported.battery_pct`
- Gateway link state is `state.reported.connected`
- Unknown fields must be ignored by both sides

## 4. BLE GATT Contract

UUIDs:
- Service `TXING Control`: `f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100`
- Characteristic `Sleep Command` (Write With Response): `f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100`
- Characteristic `State Report` (Read + Notify): `f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100`

Payloads:
- `Sleep Command` (1 byte):
  - `0x00` -> set `sleep=false`
  - `0x01` -> set `sleep=true`
- `State Report` (2 bytes):
  - byte 0: `battery_pct`
  - byte 1: `sleep` (`0x00` false, `0x01` true)

Notification behavior:
- Device notifies `State Report` on connection establishment
- Device notifies `State Report` when `sleep` changes

## 5. Gateway Required Behavior

- Subscribe to shadow delta updates for `desired.sleep`
- If `desired.sleep=false`:
  - scan/connect to Txing
  - write `Sleep Command=0x00`
  - read/subscribe `State Report` and confirm `sleep=false`
  - update `reported.sleep`, `reported.battery_pct`, `reported.connected=true`
  - keep connection maintained while desired remains false
  - reconnect on link drop
- If `desired.sleep=true`:
  - if connected, write `Sleep Command=0x01`
  - confirm report, update shadow, then disconnect
  - set `reported.connected=false`

Consistency rules:
- Shadow updates should be idempotent
- Authority is `desired.sleep` (shadow-driven intent)

## 6. Timing Expectation

Current firmware defaults used by gateway expectations:
- sleep polling period: `4 s`
- connectable listen window per wake: `500 ms`

Operational implication:
- expected wake/command latency is typically a few seconds

## 7. Acceptance Criteria

- From sleeping state, setting `desired.sleep=false` results in:
  - BLE connection established
  - device `sleep=false`
  - shadow `reported.sleep=false`
- Setting `desired.sleep=true` results in:
  - device returns to low-power periodic behavior
  - shadow `reported.sleep=true`
  - shadow `reported.connected=false`
- `reported.battery_pct` is `50` in v0.1
