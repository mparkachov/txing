# TBot Thread device architecture

> Approved planning record.

## Outcome

`tbot` is a first-class `raspi` device type that preserves the current
`unit`/bot board, motion-control, MCP, video, and REDCON 1-4 behavior while
replacing the BLE watch link and nRF54L15 MCU with stock Zephyr/OpenThread on
`xiao_nrf54lm20a/nrf54lm20a/cpuapp`.

The existing `unit` and `power-nrf` device types remain available and retain
their current behavior. `tbot` is a new type, not a migration or rename.

## Device contract

The public capability set is `sparkplug`, `thread`, `power`, `board`, `mcp`,
and `video`. The REDCON ladder is:

| REDCON | Required capabilities |
| --- | --- |
| 4 | `sparkplug`, `thread` |
| 3 | `sparkplug`, `thread`, `power` |
| 2 | `sparkplug`, `thread`, `power`, `board`, `mcp` |
| 1 | `sparkplug`, `thread`, `power`, `board`, `mcp`, `video` |

The device owns `sparkplug`, `thread`, `power`, `board`, `mcp`, and `video`
named-shadow contracts. It has no BLE capability or BLE shadow. Its board video
channel is `<device-id>-board-video`, matching Unit.

Public REDCON and MCU transport state remain separate. A requested public
REDCON 1, 2, or 3 is sent to the MCU as transport REDCON 3. The MCU reports
transport REDCON 3 while the board is powered; fresh board, MCP, and video
capability evidence determines whether Sparkplug projects public REDCON 3, 2,
or 1. Public REDCON 4 maps to MCU transport REDCON 4. The Thread adapter must
apply this normalization only to device types whose manifest supports the
four-level ladder; `power-si` and `power-nrf` remain restricted to REDCON 3/4.

Thread loss or an uncommandable CoAP endpoint makes `thread=false`, publishes
the existing offline Thread state, and causes one Sparkplug DDEATH through the
manager lifecycle. REDCON 4 or loss of fresh Thread power evidence immediately
clears board-owned capability availability. Retained board state cannot be
reused after a later wake; the daemon must publish fresh evidence.

## MCU and Thread design

The nRF54LM20A firmware is a shared stock-Zephyr/OpenThread implementation used
by `power-nrf` and `tbot`, with device-owned build profiles selecting the SRP
TXT type and product configuration. Shared behavior includes:

- versioned `TXN1` factory data containing the Thing name, Thread Active
  Operational Dataset TLVs, CoAP port, and CRC32
- `_txing-coap._udp` SRP service on port 5683 with `pv=1` and a device-specific
  `type` TXT value
- `GET /txing/v1/state` and `PUT /txing/v1/redcon`
- nPM1300 battery voltage reporting, with unavailable or failed measurements
  represented as `batteryMv: null`
- production and `sed-debug` profiles, with no BLE or Matter/CHIP stack

For `tbot`, the active-high Raspberry Pi power output is XIAO D1 / SoC
`P1.31`; the blue board LED follows the same transport state. Transport REDCON
3 drives both outputs on and uses receiver-on MTD mode `rn`. Transport REDCON 4
drives them off, returns the CoAP response, and then enters sleepy MTD mode `n`
with a 5000 ms poll period. Firmware must start safely in REDCON 4.

The existing rig Thread daemon discovers `type=tbot` SRP services only for a
matching enlisted inventory entry. Its bounded scheduler, command priority,
CoAP timeout, offline publication, and command-result behavior remain the
reliability baseline.

## Board, cloud, Office, and release integration

`tbot` uses the shared board daemon, motor hardware worker, KVS master, and
device-independent gRPC contracts with a Unit-equivalent build profile. Its
device-specific artifacts are `txing-tbot-daemon` and
`txing-tbot-hardware-worker`; the common `txing-board-kvs-master` artifact is
used unchanged. The Alpine/OpenRC install, motor failsafes, MCP session and
takeover rules, WebRTC data-channel control, MQTT fallback at REDCON 2, and KVS
video behavior match Unit.

The AWS type catalog and CloudFormation expose the tbot Thing type, capability
rules, named shadows, board video channel resource, web adapter, and enlistment
defaults. Office provides a `tbot` / `TBot` adapter with the same detail,
control, active-session, auto-open, and video behavior as Unit.

TBot has its own semantic version and `tbot-vX.Y.Z` board release stream. The
rig release must include the tbot-aware Thread adapter. Office remains
Git-published. A KVS release is required only if the shared KVS binary changes;
adding the device profile alone must not fork that binary.

## Acceptance and rollout

Automated acceptance covers catalog and enlistment data, shadow initialization,
Thread discovery/type matching, per-device REDCON normalization, Sparkplug
aggregation and lifecycle, MCU factory/storage and firmware profiles, board
builds and cross-userland smoke tests, release packaging, and Office behavior.
Existing Unit, power-nrf, and power-si contract tests must continue to pass.

Milestone completion additionally requires the silent production firmware and
final hardware in the intended enclosure to demonstrate:

- valid TXN1 provisioning, Thread attach, and matching active SRP registration
- receiver-off sleepy MTD operation at REDCON 4 and indirect delivery within
  the 5-second poll bound
- repeated REDCON 4 to 3/2/1 to 4 cycles, correct `rn`/`n` transitions, and
  correct D1/P1.31 power switching
- Raspberry Pi cold boot, Wi-Fi recovery, and fresh Board/MCP/Video capability
  convergence
- battery telemetry, MCP lease/takeover/failsafe motion control, live KVS video,
  multiple viewers, and the existing sub-800 ms p95 video latency target on
  target links
- reliable operation with the final enclosure-compatible antenna

Rollout is manual and forward-only: the operator deploys the approved AWS
catalog changes, publishes the required rig, tbot, and Office releases, enlists
the device, installs the board and rig artifacts, enables Thread connectivity
against an already configured colocated OTBR, provisions the Thread dataset,
and flashes firmware. Thread dataset credentials must not be committed.

## Non-goals

- Renaming, migrating, or removing `unit`
- Changing `power-nrf` or `power-si` product behavior
- Retaining BLE as a tbot fallback or compatibility transport
- Provisioning or embedding an OTBR
- Adding Matter/CHIP, a second video path, or new MCP control semantics
- Automating AWS deployment, board maintenance, MCU provisioning, or flashing

## Tracking

- [Milestone 3: TBot Thread device type](https://github.com/mparkachov/txing/milestone/3)
- [#120: Establish the tbot device and operator contracts](https://github.com/mparkachov/txing/issues/120)
- [#123: Deliver shared nRF54LM20A firmware for tbot](https://github.com/mparkachov/txing/issues/123)
- [#122: Operate the tbot lifecycle over Thread](https://github.com/mparkachov/txing/issues/122)
- [#124: Ship the tbot board runtime and release artifacts](https://github.com/mparkachov/txing/issues/124)
- [#121: Validate tbot end to end in the target enclosure](https://github.com/mparkachov/txing/issues/121)
