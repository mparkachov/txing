---
id: doc-33
title: power-nrf Thread device architecture
type: specification
created_date: '2026-08-01 12:22'
---

# power-nrf Thread device architecture

## Scope

`power-nrf` is a first-class `raspi` device type for the stock Zephyr
`xiao_nrf54lm20a/nrf54lm20a/cpuapp` board target. It provides the same
Sparkplug, Thread, Power, and REDCON 3/4 contract as `power-si`, but uses a
standalone Thread/CoAP firmware app and includes neither Matter/CHIP nor BLE.

The device starts receiver-on only long enough to attach to Thread and register
its SRP service. It then operates as an MTD sleepy end device using a 5 second
poll period. REDCON 3 enables power capability, drives XIAO header pin A1 (SoC
GPIO `P1.31`) and blue `led0`, and changes Thread mode to `rn`. REDCON 4
disables those outputs, returns the CoAP response, and then returns Thread mode
to `n`. The stock Zephyr board definition calls A1 connector index 1, or D1,
internally.

## Device and network contract

- The display name is **Power nRF** and both the type slug and DNS-SD TXT type
  are `power-nrf`.
- CoAP version-1 endpoints are `GET /txing/v1/state` and
  `PUT /txing/v1/redcon`; only REDCON 3 and 4 are accepted.
- The SRP service is `_txing-coap._udp` on port 5683 with TXT records
  `type=power-nrf` and `pv=1`.
- Capabilities are `sparkplug`, `thread`, and `power`. REDCON 4 exposes
  Sparkplug and Thread; REDCON 3 also exposes Power.
- The shared rig Thread adapter supports exactly `power-si` and `power-nrf`.
  Discovery accepts both TXT types, but a discovered endpoint is used only when
  its TXT type matches the enlisted inventory type.

## Firmware and provisioning

The firmware is a new stock-Zephyr application. The board target, device-tree
bindings, radio support, PMIC measurement interface, and OpenOCD runner are
all supplied by upstream Zephyr. No local board definition or downstream radio
patch is introduced.

Factory data uses a versioned `TXN1` record with magic, version, Thing name,
Thread Active Operational Dataset TLVs, CoAP port, and CRC32. The stock board
36 KiB storage region is split into an 8 KiB read-only factory partition and a
28 KiB OpenThread settings partition. The shared MCU driver provides
`power-nrf::mcu::nve <thing-name> <dataset-tlvs>` and an Intel-HEX writer. The
existing `TXR1` and `TXT1` records are unchanged.

Battery millivolts are read on demand from the nPM1300 measurement interface
and published through the existing `power` named shadow. Failed or unavailable
measurement is represented as `batteryMv: null`; no synthetic value is used.

## Verification and rollout

Automated coverage validates factory records and Intel-HEX addressing, storage
boundaries, firmware SED configuration and REDCON transitions, absence of
Matter/BLE, battery failure semantics, mixed-type rig discovery, and every
type-integration surface. Release, debug, and SED-debug images must build with
the updated stock Zephyr checkout and its stock OpenOCD invocation.

Rollout is user-operated: deploy the updated catalog through the existing AWS
flow, enlist a `power-nrf` Thing, provision its factory HEX and Thread dataset,
flash it manually, and enable the existing Thread daemon on the colocated OTBR
rig. Hardware acceptance verifies SRP registration, SED mode and poll period,
OTBR child role, REDCON output/mode changes, PMIC telemetry, and Office-visible
Thread and Power state.

### Hardware acceptance result — blocked (2026-08-02)

The target enclosure cannot accommodate the external IPEX4 antenna documented
for the XIAO nRF54LM20A Sense.  In the target RF environment, the device
attached and registered SRP only at very short range while receiver-on (`rn`).
After the specified transition to sleepy MTD mode (`n`), no reliable indirect
delivery/reachability was validated, including at very short range.  Runtime
radio transmit-power adjustment did not change this result and does not persist
over reset.  The same OTBR and environment work with `power-si`.

The product is therefore blocked on a board/enclosure-compatible RF design.
Do not deploy, enlist, or release `power-nrf` for this enclosure.  REDCON,
nPM1300, and Office hardware acceptance remain unproven because their CoAP
path depends on the failed SED delivery requirement.  A successor hardware
trial must use an enclosure-compatible external antenna, a suitable integrated
antenna, or a validated custom antenna design, and repeat the full acceptance
matrix in `devices/power-nrf/README.md`.

## GitHub issue references

- [#95 — Integrate power-nrf contracts and control plane](https://github.com/mparkachov/txing/issues/95) (migrated from `TASK-24`)
- [#96 — Add power-nrf stock-Zephyr builds and factory provisioning](https://github.com/mparkachov/txing/issues/96) (migrated from `TASK-25`)
- [#98 — Implement power-nrf Thread SED CoAP firmware](https://github.com/mparkachov/txing/issues/98) (migrated from `TASK-26`)
- [#100 — Publish power-nrf nPM1300 battery telemetry](https://github.com/mparkachov/txing/issues/100) (migrated from `TASK-27`)
- [#101 — Generalize rig Thread discovery for power-nrf](https://github.com/mparkachov/txing/issues/101) (migrated from `TASK-28`)
- [#102 — Validate and document power-nrf rollout](https://github.com/mparkachov/txing/issues/102) (migrated from `TASK-29`)
