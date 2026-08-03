---
id: doc-22
title: 'Milestone: power-si Thread device type'
type: specification
created_date: '2026-06-20 07:11'
updated_date: '2026-07-27 19:41'
tags:
  - power-si
  - thread
  - milestone
---
# Milestone: power-si Thread device type

## Goal

Deliver `power-si` as a first-class txing device type equivalent to `power` at the product level, implemented on XIAO MG24 with stock Zephyr and OpenThread over Thread and CoAP.

## Scope

This milestone delivers the `power-si` catalog and Office contract, stock-Zephyr firmware and TXT1 provisioning path, the rig Thread connectivity daemon, Sparkplug lifecycle integration, bounded-latency SED operation, battery reporting, release packaging, and operator documentation for a preconfigured OTBR.

It does not add Matter, automate OTBR installation, automate cloud deployment, automate hardware flashing, or migrate the existing nRF and BLE `power` device.

## Completed Tasks

- `TASK-21.1` registered `power-si` in manifests, schemas, shared AWS catalog generation, and Office.
- `TASK-21.2` delivered XIAO MG24 firmware, the `TXT1` factory record, and stock-Zephyr build and pyOCD provisioning flow.
- `TASK-21.3` added the Thread connectivity daemon, CoAP protocol client, direct local SRP discovery, IPC publishing, and manager transport evidence.
- `TASK-21.4` delivered release and operations documentation plus end-to-end manual hardware acceptance.
- `TASK-21.5` delivered the bounded-latency 5000 ms SED path and its stock-Silabs radio validation.
- `TASK-21.6` aligned per-device MQTT session lifecycle with DDEATH and DBIRTH evidence.
- `TASK-21.7` recorded and corrected invalid AC-current measurement history.
- `TASK-21.8` validated the silent SED functional overlay before its later consolidation.
- `TASK-21.9` added on-demand calibrated battery millivolt reporting.
- `TASK-21.10` prioritized Thread REDCON commands over maintenance polling and fixed the REDCON 4 response ordering.
- `TASK-21.11` consolidated the validated SED functionality and battery reporting into the final release profile and removed the redundant `sed-current` profile.

## Completion Evidence

Automated evidence covers MCU factory and SED configuration tests, release and `sed-debug` XIAO MG24 builds, rig Go tests including scheduler priority and lifecycle behavior, shared AWS catalog and registry coverage, and Office adapter, Thread-capability, and named-shadow tests.

Manual hardware evidence covers TXT1 provisioning, final firmware flash, fresh SRP registration, SED `n` mode with a 5000 ms poll period and `R=0` at REDCON `4`, receiver-on `rn` with `R=1` at REDCON `3`, queued indirect delivery, direct rig CoAP discovery, Office Thread capability and REDCON projection, D1 and LED state, battery shadow publication, and direct Sparkplug DDEATH, DBIRTH, and confirmed DDATA captures. The final command-scheduling evidence recorded REDCON `4` to `3` confirmation within one child poll and REDCON `3` to `4` confirmation within receiver-on processing margin.

## Operational Notes

The final release and `sed-debug` apply a focused RadioAES CCM candidate only while building and reverse it before the helper returns, leaving the shared Zephyr and Silabs HAL checkouts stock. The candidate remains downstream pending upstream acceptance of an equivalent fix.

The Thread daemon queries the colocated OTBR SRP registry through `ot-ctl`; it does not require mDNS publication or host DNS records. Operators retain responsibility for OTBR readiness, credentials, factory provisioning, and firmware flashing. Thread dataset TLVs remain secret operator material and must not be committed.

## Required References

- Architecture: `doc-21`
- Parent task: `TASK-21`
- Product operations: `devices/power-si/README.md`
- Rig operations: `docs/components/rig.md`
- MCU implementation: `docs/components/mcu.md`
