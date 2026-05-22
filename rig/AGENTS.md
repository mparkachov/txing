# rig subproject guide

## Scope
- This directory contains standalone Go daemons and host tooling for `raspi`
  rigs.
- Raspi rig responsibilities include direct AWS IoT MQTT integration,
  Sparkplug lifecycle publication, and BLE communication with managed MCUs.
- The AWS-hosted `cloud` rig and `cloud-mcu` Lambda runtime lives under
  `devices/cloud-mcu/`.

## Notes
- Run rig Go and `just` commands from `rig/` or through the repository root
  aliases.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../devices/unit/aws/*-shadow.schema.json` as the canonical shadow JSON structure for the current `unit` device type.
- `rig` owns Sparkplug MQTT publication plus the `mcu` named shadow contract; the AWS-side `sparkplug` named shadow is witness-owned projection state.

## Stability
- Rig services are not user-serviced applications. Treat stability as a hard requirement: every long-running BLE, AWS, network, IPC, and supervisor-facing loop must survive transient failures with bounded retries, backoff, and log throttling where repeated failures are expected.
- Avoid resource churn in retry paths. Reuse long-lived clients/managers where the underlying library supports it, and make repeated failures slower rather than louder.

## Shared workflow
- Follow the repository-level workflow in `../AGENTS.md`.
