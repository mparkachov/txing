# Txing Thing Shadow Model

This document defines the current AWS IoT Thing Shadow contract for the `unit` device type.

## Status

- The txing device no longer uses the classic unnamed shadow.
- Sparkplug `DCMD.redcon` is the only authoritative external lifecycle intent path.
- Shadows are reported-only read models and restart caches; no `desired` lifecycle fields are used.
- Video runtime state remains outside Thing Shadow and is carried by retained MQTT video topics plus board MCP `robot.get_state`.

## Named Shadows

Each txing thing uses these named shadows:

- `sparkplug`: rig-owned lifecycle reflection, `state.reported.redcon`.
- `device`: rig-owned shared metrics, `state.reported.batteryMv`.
- `mcu`: rig-owned MCU state, `state.reported.power` and `state.reported.online`.
- `board`: board-owned board state, `state.reported.power` and `state.reported.wifi`.

Schema/default files live under `devices/unit/aws/`:

- `sparkplug-shadow.schema.json`, `default-sparkplug-shadow.json`
- `device-shadow.schema.json`, `default-device-shadow.json`
- `mcu-shadow.schema.json`, `default-mcu-shadow.json`
- `board-shadow.schema.json`, `default-board-shadow.json`

## Ownership

- `rig` calculates REDCON and writes the `sparkplug` named shadow.
- `rig` writes `device.batteryMv` and the `mcu` named shadow.
- `board` writes the `board` named shadow.
- Web reads named shadows and publishes lifecycle commands through Sparkplug MQTT `DCMD.redcon`; it does not write shadow desired state.

## Field Semantics

- `sparkplug.state.reported.redcon` (`1..4`) is the rig-derived readiness summary:
  - `4`: Green / `Cold Camp` / MCU sleep state or BLE unavailable
  - `3`: Yellow / `Torch-Up` / MCU wakeup state with BLE reachability, but MCP unavailable
  - `2`: Orange/Amber / `Ember Watch` / MCU wakeup state with BLE reachability and MCP availability, but retained video status not ready
  - `1`: Red / `Hot Rig` / MCU wakeup state with BLE reachability, MCP availability, and retained video status ready
- `device.state.reported.batteryMv` is the latest MCU battery estimate observed by rig.
- `mcu.state.reported.power=true` means the external wakeup state.
- `mcu.state.reported.power=false` means the external sleep state with periodic `5 s` BLE rendezvous wakeups.
- `mcu.state.reported.online` is rig-observed BLE reachability.
- `board.state.reported.power` is best-effort board power state; stale `true` must not be treated as authoritative after a hard power cut.
- `board.state.reported.wifi.online`, `ipv4`, and `ipv6` are refreshed by the board control loop.

## AWS IoT Note

AWS IoT Thing Shadows do not enforce custom JSON schema automatically. Project code and tests validate payloads before publishing.
