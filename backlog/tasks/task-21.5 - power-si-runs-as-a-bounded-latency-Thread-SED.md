---
id: TASK-21.5
title: power-si runs as a bounded-latency Thread SED
status: In Progress
assignee:
  - '@Codex'
created_date: '2026-06-26 16:46'
updated_date: '2026-06-26 17:00'
labels: []
milestone: m-0
dependencies:
  - TASK-21.2
  - TASK-21.3
references:
  - devices/power-si/mcu/src/main.c
  - devices/power-si/mcu/zephyr/prj.conf
  - rig/internal/rigconfig/config.go
  - rig/rig-daemon.env.template
documentation:
  - >-
    backlog/docs/architecture/power-si-thread-device/doc-21 -
    power-si-Thread-device-type-architecture.md
  - >-
    backlog/docs/milestones/power-si-thread-device/doc-22 -
    Milestone-power-si-Thread-device-type.md
parent_task_id: TASK-21
priority: high
ordinal: 47500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Convert power-si from the temporary non-sleeping MTD profile to the intended stock Zephyr/OpenThread Sleepy End Device profile. The device must keep SRP registration for _txing-coap._udp, continue using CoAP on port 5683, and preserve synchronous rig REDCON behavior by using a 5 second SED poll period and a 12 second rig Thread CoAP timeout.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Firmware builds as stock Zephyr/OpenThread MTD SED with a 5000 ms poll period and no application path forcing receiver-on mode.
- [ ] #2 Debug hardware evidence shows ot mode reports n, ot pollperiod reports 5000, OTBR child table shows receiver-on flag false, and SRP service power-si._txing-coap._udp.default.service.arpa remains deleted:false on port 5683.
- [x] #3 Rig Thread defaults support bounded synchronous control of a 5 second SED with a 12 second CoAP timeout, without changing BLE behavior or adding async command semantics.
- [x] #4 Tests or static checks cover the SED build/config contract and updated rig Thread timeout default; existing Thread CoAP and REDCON tests still pass.
- [x] #5 Docs no longer describe power-si as receiver-on MTD and include the manual debug commands needed for SED hardware acceptance.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the current power-si OpenThread mode setup, rig Thread timeout defaults, and existing docs/tests that mention receiver-on MTD behavior.
2. Change power-si firmware to use stock Zephyr/OpenThread SED behavior with a 5000 ms poll period and no application override forcing receiver-on mode.
3. Raise rig Thread CoAP default timeout to 12000 ms, update service templates/docs, and keep synchronous command behavior unchanged.
4. Add focused checks or tests for the SED config contract and rig timeout default, then run the relevant MCU/rig/doc validation that can run without flashing hardware.
5. Update task evidence and leave hardware-only acceptance unchecked unless the operator provides manual debug evidence.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementation update (2026-06-26):
- `power-si` release/debug firmware now enables `CONFIG_OPENTHREAD_MTD_SED=y` and `CONFIG_OPENTHREAD_POLL_PERIOD=5000`.
- The app no longer forces receiver-on mode. Manual Thread startup now applies `mRxOnWhenIdle=false`, MTD mode, full network data, and `otLinkSetPollPeriod(..., CONFIG_OPENTHREAD_POLL_PERIOD)` before enabling Thread.
- Rig Thread CoAP default timeout is now 12000 ms in code and `rig/rig-daemon.env.template`; BLE timeout/default behavior is unchanged and Thread commands remain synchronous.
- Docs now describe `power-si` as a 5 second poll Thread SED and include debug evidence commands: `ot mode`, `ot pollperiod`, OTBR `child table`, and SRP service checks.

Validation evidence:
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `go test ./internal/rigconfig ./internal/thread` passed.
- `just rig::test` passed across all rig packages.
- `just power-si::mcu::build` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24/zephyr/zephyr.hex`.
- `just power-si::mcu::build-debug` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- Release and debug generated `.config` files both contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, and `CONFIG_OPENTHREAD_POLL_PERIOD=5000`.
- Stale-doc grep for current receiver-on/default-timeout wording returned no matches in active docs and rig/device sources.
- `git diff --check` passed.
- `python3 -m pytest ...` was not run because `pytest` is not installed in the active Python environment; the explicit unittest and Go validation above were used instead.

Remaining hardware-only evidence for AC #2:
- User-run debug firmware flash and UART/OTBR checks must show `ot mode` = `n`, `ot pollperiod` = `5000`, OTBR child-table receiver-on flag `R=0`, and SRP service `power-si._txing-coap._udp.default.service.arpa` still `deleted:false` on port 5683.

Continuation audit (2026-06-26): current software/build/docs evidence still satisfies AC #1, #3, #4, and #5. Added a minimal TASK-21.5 SED evidence block to devices/power-si/README.md. AC #2 remains open until the operator captures debug-image hardware output showing ot state=child, ot mode=n, ot pollperiod=5000, OTBR child table R=0 for the XIAO MG24, and SRP service deleted:false on port 5683.
<!-- SECTION:NOTES:END -->
