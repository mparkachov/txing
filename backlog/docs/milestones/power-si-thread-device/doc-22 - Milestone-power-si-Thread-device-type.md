---
id: doc-22
title: 'Milestone: power-si Thread device type'
type: specification
created_date: '2026-06-20 07:11'
updated_date: '2026-06-20 07:13'
tags:
  - power-si
  - thread
  - milestone
---
# Milestone: power-si Thread device type

## Goal

Introduce `power-si` as a first-class txing device type that behaves like the existing `power` device at the product level while using XIAO MG24, stock Zephyr/OpenThread, and Thread/CoAP transport.

## Scope

This milestone covers the device catalog/UI contract, XIAO MG24 firmware and factory provisioning path, rig Thread connectivity daemon, Sparkplug manager integration, release packaging, and operational documentation required to run the device against an already configured OTBR.

This milestone does not cover Matter support, OTBR installation automation, cloud resource deployment, automatic firmware flashing, or migration of the existing nRF `power` device.

## Implementation tasks

- `TASK-21.1` - Register `power-si` across device contracts, catalog, shadow schemas, and Office UI.
- `TASK-21.2` - Build the XIAO MG24 stock Zephyr/OpenThread firmware and factory provisioning surface.
- `TASK-21.3` - Add rig Thread connectivity and Sparkplug manager transport integration.
- `TASK-21.4` - Package and document the Thread runtime with manual provisioning and hardware acceptance evidence.

## Acceptance summary

The milestone is complete when `power-si` can be built/provisioned manually, discovered through SRP on a Thread network, controlled by the rig through CoAP REDCON commands, represented correctly in AWS/catalog and Office, and validated by automated tests plus documented manual hardware acceptance.

## Required references

- Architecture spec: `backlog/docs/architecture/power-si-thread-device/doc-21 - power-si-Thread-device-type-architecture.md`
- Parent milestone task: `TASK-21`
- Existing power contract: `devices/power/manifest.toml`
- Rig IPC contract: `rig/internal/protocol`
- Arduino physical PoC: `tmp/ot_ping/ot_ping.ino`
