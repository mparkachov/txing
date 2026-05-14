# rig subproject guide

## Scope
- This directory contains the Python rig runtime for Raspberry Pi 5.
- Rig responsibilities include direct AWS IoT MQTT integration and BLE communication with the MCU.

## Notes
- Run Python and `uv` commands from `rig/`.
- Follow repository-level rule: do not create commits unless explicitly requested by the user.
- Use `../devices/unit/aws/*-shadow.schema.json` as the canonical shadow JSON structure for the current `unit` device type.
- `rig` owns Sparkplug MQTT publication plus the `mcu` named shadow contract; the AWS-side `sparkplug` named shadow is witness-owned projection state.

## Stability
- Rig services are not user-serviced applications. Treat stability as a hard requirement: every long-running BLE, AWS, network, IPC, and supervisor-facing loop must survive transient failures with bounded retries, backoff, and log throttling where repeated failures are expected.
- Avoid resource churn in retry paths. Reuse long-lived clients/managers where the underlying library supports it, and make repeated failures slower rather than louder.

## Shared workflow
- Follow the repository-level Beads workflow in `../AGENTS.md`.
- If a rig-specific task is created under a shared epic, mention `rig/` in the Beads title or description so ownership is obvious.
