---
id: doc-21
title: power-si Thread device type architecture
type: specification
created_date: '2026-06-20 07:11'
updated_date: '2026-06-20 07:11'
tags:
  - power-si
  - thread
  - mcu
  - rig
  - architecture
---
# power-si Thread device type architecture

## Summary

`power-si` is a new txing device type that provides the same product-level behavior as the existing `power` device while replacing the nRF/BLE transport with Seeed XIAO MG24, stock Zephyr, OpenThread, and CoAP over Thread. The device is Thread-only for this milestone; Matter/CHIP commissioning, clusters, and fabrics are explicitly out of scope.

The public device type slug is `power-si`. The device participates in the normal txing Sparkplug lifecycle through the rig, publishes a power shadow with battery state, and exposes REDCON 4/3 transitions equivalent to the current power device.

## Device contract

The `power-si` manifest must declare capabilities `sparkplug`, `thread`, and `power`, with compatible rig type `raspi`. REDCON level 4 requires `sparkplug` and `thread`; REDCON level 3 requires `sparkplug`, `thread`, and `power`. The device owns named shadows for `sparkplug`, `thread`, and `power`.

The Office UI should reuse the current power model and panel behavior while registering a distinct `power-si` adapter with display name `Power SI`. AWS/catalog generation must include `power-si` as a first-class device type, not as an alias of `power`.

## Firmware and factory data

Firmware targets the stock Zephyr board `xiao_mg24` using the repo stock Zephyr workflow and does not enable Matter. The implementation is a Thread MTD Sleepy End Device with `mRxOnWhenIdle=false`, full network data, and a `5000 ms` poll period so it matches the original low-power Thread intent while keeping bounded rig command latency.

Factory data for `power-si` uses a versioned `TXT1` record stored in MG24 nonvolatile flash. The record contains magic/version, Thing name, Thread Active Operational Dataset TLVs, CoAP port, and CRC. The existing nRF `TXR1` NVE format and commands remain unchanged.

The XIAO MG24 flash layout reserves an 8 KiB txing factory partition and a separate 16 KiB Zephyr/OpenThread settings partition aligned to the MG24 8 KiB erase block size. The settings partition must remain at least two erase sectors for Zephyr NVS, so the layout takes one erase block from the board's unused secondary image slot rather than splitting the stock 16 KiB storage area into two invalid 8 KiB regions. Real Thread dataset TLVs are secrets and must not be committed.

D1 is the controlled power output. The board LED follows power state using the board active-low LED wiring.

## Thread application protocol

The device registers SRP service `_txing-coap._udp`, with service instance equal to the txing Thing name, port `5683`, and TXT metadata including `type=power-si` and a protocol version.

The rig communicates with Confirmable CoAP requests using JSON payloads:

- `GET /txing/v1/state` returns Thing name, protocol version, REDCON level, and battery millivolts when available.
- `PUT /txing/v1/redcon` accepts REDCON 3 or 4, applies the output/LED state before responding, and returns the resulting state.
- Unsupported levels and malformed payloads return CoAP 4.xx errors.

## Rig runtime

Add `txing-thread-connectivity` as a third rig daemon alongside Sparkplug manager and BLE connectivity. The daemon assumes an externally configured OTBR and does not install or configure OTBR itself.

Discovery uses SRP/DNS-SD under `default.service.arpa` and resolves PTR/SRV/TXT/AAAA records for `_txing-coap._udp`. The daemon filters discovered services to `type=power-si`, maps service instances to Thing names, polls state over CoAP, and sends REDCON commands over CoAP.

The daemon publishes capability state, command results, thread shadow updates, and power shadow updates through the existing rig v2 local IPC protocol. Sparkplug manager transport handling must be generalized so BLE behavior remains unchanged while `power-si` uses Thread REDCON evidence for lifecycle and capability state.

Because `power-si` sleeps between Thread polls, rig Thread CoAP requests remain synchronous but use a default `12000 ms` timeout. This preserves the existing command-result contract while allowing one 5 second sleepy poll window plus network jitter.

## Operations and acceptance

Release and rig install documentation must include the third daemon, OTBR prerequisites, manual provisioning, and manual flashing/provisioning commands. Agents must not run firmware flashing or factory-data programming commands.

Hardware acceptance requires provisioning factory data, manually flashing firmware, verifying SRP registration, rig discovery, REDCON 4/3 transitions, D1 output behavior, battery shadow updates, and Sparkplug birth/data/death behavior.

## References

- `devices/power/manifest.toml`
- `devices/power/README.md`
- `devices/common/mcu/scripts/stock_zephyr_mcu.py`
- `rig/internal/protocol`
- `tmp/ot_ping/ot_ping.ino`
