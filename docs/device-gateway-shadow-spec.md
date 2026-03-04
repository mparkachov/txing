# Txing Gateway Contract (Shadow + BLE) v0.3

This document is the integration contract for the gateway team only.
Build, flash, and local developer commands are intentionally out of scope and live in `README.md`.

## 1. Scope

Contract between:
- Txing firmware (BLE peripheral)
- BLE gateway service (direct MQTT client to AWS IoT)
- AWS IoT Thing Shadow for thing name `txing`

Authoritative shadow schema:
- `./txing-shadow.schema.json`
- Example default document: `../aws/default-shadow.json`

High-level architecture:
- AWS IoT Device Shadow -> MQTT -> gw -> BLE -> mcu

## 2. Design Decision: Shadow Ownership

- `gw` is the source of truth for MCU shadow data.
- Only `gw` may define/evolve the `mcu.*` subtree contract.
- `gw` communicates with the physical MCU over BLE and reflects MCU state in shadow.

## 3. Device State Exposed to Gateway

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

## 4. Shadow Contract

Thing name: `txing`
Shadow type: classic (unnamed) Thing Shadow (`$aws/things/txing/shadow/*`)

Authoritative JSON schema: `./txing-shadow.schema.json`

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
        "batteryPercent": 50
      }
    }
  }
}
```

Rules:
- Command input is `state.desired.mcu.power`
- Confirmed device state is `state.reported.mcu.power`
- Battery value is `state.reported.mcu.batteryPercent`
- Unknown fields must be ignored by both sides

Mapping from firmware state:
- `mcu.power = !sleep`
- `mcu.power=true` means MCU is awake/active
- `mcu.power=false` means MCU is in low-power sleep behavior

## 5. BLE GATT Contract

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

## 6. Gateway Required Behavior

- Subscribe to shadow delta updates for `desired.mcu.power`
- If `desired.mcu.power=true`:
  - scan/connect to Txing
  - write `Sleep Command=0x00` (`sleep=false`)
  - read/subscribe `State Report` and confirm `mcu.power=true`
  - update `reported.mcu.power=true`, `reported.mcu.batteryPercent=50`
  - keep connection maintained while desired remains true
  - reconnect on link drop
- If `desired.mcu.power=false`:
  - if connected, write `Sleep Command=0x01` (`sleep=true`)
  - confirm report, update shadow, then disconnect
  - set `reported.mcu.power=false`

Consistency rules:
- Shadow updates should be idempotent
- Authority is `desired.mcu.power` (shadow-driven intent)

## 7. Timing Expectation

Current firmware defaults used by gateway expectations:
- sleep polling period: `4 s`
- connectable listen window per wake: `500 ms`

Operational implication:
- expected wake/command latency is typically a few seconds

## 8. Acceptance Criteria

- From sleeping state, setting `desired.mcu.power=true` results in:
  - BLE connection established
  - device `sleep=false`
  - shadow `reported.mcu.power=true`
- Setting `desired.mcu.power=false` results in:
  - device returns to low-power periodic behavior
  - shadow `reported.mcu.power=false`
- `reported.mcu.batteryPercent` is `50` in v0.3
