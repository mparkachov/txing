---
id: doc-21
title: power-si Thread device type architecture
type: specification
created_date: '2026-06-20 07:11'
updated_date: '2026-07-27 19:41'
tags:
  - power-si
  - thread
  - mcu
  - rig
  - architecture
---
# power-si Thread device type architecture

## Summary

`power-si` is a first-class txing device type with the product-level behavior of `power`, implemented on Seeed XIAO MG24 with stock Zephyr, OpenThread, and CoAP over Thread. It is Thread-only. Matter and CHIP commissioning, clusters, and fabrics are out of scope.

The public type slug is `power-si`. The device participates in the normal txing Sparkplug lifecycle through the rig, publishes power state and optional battery millivolts, and exposes REDCON `4` and `3` transitions.

## Device Contract

The manifest declares capabilities `sparkplug`, `thread`, and `power`, with compatible rig type `raspi`. REDCON `4` requires `sparkplug` and `thread`; REDCON `3` additionally requires `power`. Named shadows are `sparkplug`, `thread`, and `power`.

Office registers a distinct `Power SI` adapter that reuses the existing power model and panel. AWS catalog generation includes `power-si` as a first-class type rather than an alias of `power`.

## Firmware And Factory Data

Firmware targets the stock Zephyr `xiao_mg24` board through the repository stock-Zephyr workflow. It is an OpenThread MTD Sleepy End Device with a `5000 ms` poll period and no Matter stack. Startup uses a temporary receiver-on SRP bootstrap to attach and register the service, then changes the existing child to sleepy `n` mode with full network data.

The final release and `sed-debug` profiles use a bounded requested-link recovery policy after the bootstrap. REDCON `3` requests receiver-on MTD (`rn`) for immediate follow-up control. REDCON `4` sends its confirmed CoAP response while receiver-on, waits a bounded `100 ms` grace, then returns to sleepy MTD (`n`). The existing child and SRP registration remain in place. Ordinary `debug` retains the diagnostic receiver-on fallback and does not use the live REDCON link policy.

The stock Silabs hardware TX-security path needs a focused downstream RadioAES CCM candidate for encrypted zero-payload messages with a MIC. The candidate is applied only to the owning Silabs HAL checkout during final-release and `sed-debug` builds, then reversed before the helper returns. It preserves `IEEE802154_HW_TX_SEC`, normal driver retry behavior, emitted MIC post-processing, and stock sources outside the build. It remains a downstream candidate until upstream accepts an equivalent fix.

Factory data uses a versioned `TXT1` record in MG24 flash. It contains magic and version, Thing name, Thread Active Operational Dataset TLVs, CoAP port, and CRC. The nRF `TXR1` format and commands are unchanged. The XIAO MG24 layout reserves an 8 KiB factory partition and a distinct 16 KiB Zephyr and OpenThread settings partition aligned to 8 KiB erase blocks. Thread dataset TLVs are credentials and must never be committed.

D1 is the controlled active-high power output. The board active-low LED follows the same REDCON power state. The final release samples the battery divider on demand and reports `batteryMv`; diagnostic profiles report `null`.

## Thread Application Protocol

The device registers `_txing-coap._udp` through SRP. Its service instance is the Thing name, the port is `5683`, and TXT metadata includes `type=power-si`, `pv=1`, and the shared SED-policy profile marker for final-release and `sed-debug` images.

The rig uses Confirmable CoAP JSON requests:

- `GET /txing/v1/state` returns Thing name, protocol version, REDCON level, and battery millivolts when available.
- `PUT /txing/v1/redcon` accepts REDCON `3` or `4`, applies the output before responding, and returns the resulting state.
- Malformed input and unsupported levels return CoAP `4.xx` responses.

## Rig Runtime

`txing-thread-connectivity` is the third rig daemon alongside Sparkplug manager and BLE connectivity. It assumes an already configured OTBR on the same host and reads the active SRP registry through `ot-ctl`. It does not install OTBR, require mDNS publication, or depend on host DNS resolver records.

The daemon filters `_txing-coap._udp` services to `type=power-si`, maps service instances to Thing names, polls CoAP state, and sends REDCON commands. It publishes capability state, command results, the Thread named shadow, and optional power battery shadow updates through the existing rig v2 IPC contract.

Thread capability evidence creates Sparkplug device sessions. Loss of validated Thread CoAP evidence publishes one DDEATH and disconnects that device session; recovery creates a new session before DBIRTH. This keeps AWS IoT device connection state aligned with Office transport availability.

Thread maintenance runs outside the IPC receive path. A bounded per-device scheduler coalesces discovery and state polling, prioritizes commands, and cancels an in-flight same-device maintenance GET when a REDCON command arrives. The CoAP attempt timeout remains `12000 ms`, permitting one sleepy poll window plus network jitter while retaining synchronous confirmed-state command semantics.

## Operations And Acceptance

The rig release includes Sparkplug manager, BLE connectivity, and Thread connectivity artifacts and services. Operators manually provision `TXT1`, build and flash firmware, and verify OTBR before use. Agents do not configure OTBR or flash hardware.

Validated hardware evidence covers fresh SRP registration, SED `n` mode with `R=0` at REDCON `4`, receiver-on `rn` mode with `R=1` at REDCON `3`, queued indirect delivery, rig discovery, Thread and power shadow projection, direct D1 and LED state, battery measurement, and Sparkplug DDEATH, DBIRTH, and confirmed DDATA lifecycle events. Final scheduler evidence recorded REDCON `4` to `3` confirmations within one 5000 ms poll and REDCON `3` to `4` confirmations while receiver-on.

## Non-Goals

This design does not automate OTBR installation, firmware flashing, factory provisioning, or cloud deployment. It does not migrate the existing nRF and BLE `power` device and does not introduce Matter.
