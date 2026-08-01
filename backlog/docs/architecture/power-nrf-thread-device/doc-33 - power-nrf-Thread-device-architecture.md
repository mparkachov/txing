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
poll period. REDCON 3 enables power capability, drives XIAO D1 and blue `led0`,
and changes Thread mode to `rn`. REDCON 4 disables those outputs, returns the
CoAP response, and then returns Thread mode to `n`.

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
