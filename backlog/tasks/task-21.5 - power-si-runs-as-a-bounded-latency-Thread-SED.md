---
id: TASK-21.5
title: power-si runs as a bounded-latency Thread SED
status: In Progress
assignee:
  - '@Codex'
created_date: '2026-06-26 16:46'
updated_date: '2026-07-18 11:15'
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
- [ ] #1 Firmware builds as stock Zephyr/OpenThread MTD SED with a 5000 ms poll period and no steady-state application path leaving the device receiver-on after SRP bootstrap.
- [x] #2 Debug hardware evidence shows ot mode reports n, ot pollperiod reports 5000, OTBR child table shows receiver-on flag false, and SRP service power-si._txing-coap._udp.default.service.arpa remains deleted:false on port 5683.
- [x] #3 Rig Thread defaults support bounded synchronous control of a 5 second SED with a 12 second CoAP timeout, without changing BLE behavior or adding async command semantics.
- [x] #4 Tests or static checks cover the SED build/config contract and updated rig Thread timeout default; existing Thread CoAP and REDCON tests still pass.
- [x] #5 Docs no longer describe power-si as receiver-on MTD and include the manual debug commands needed for SED hardware acceptance.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Keep release and ordinary debug on their existing stock Zephyr fallback policy, while sed-debug and sed-current use the isolated Silabs CCM candidate only for their own builds.
2. Keep the validated bounded SED-only recovery policy in both candidate profiles: after the post-SRP transition, retry a lost attachment in SED mode at most three times with backoff and never restore receiver-on mode.
3. Make sed-current a silent current-measurement image that retains only the minimum power-si behavior needed for representative network current: Thread, SRP, CoAP, safe GPIO output state, Zephyr PM, and tickless idle; disable UART, console, shell, logging, OpenThread debug, printk, and boot output.
4. Validate profile configuration statically, build sed-current through the isolated candidate patch path, verify that the Silabs HAL checkout returns to clean stock state, and document manual current-measurement evidence.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial implementation update (2026-06-26):
- `power-si` release/debug firmware enables `CONFIG_OPENTHREAD_MTD_SED=y` and `CONFIG_OPENTHREAD_POLL_PERIOD=5000`.
- Rig Thread CoAP default timeout is 12000 ms in code and `rig/rig-daemon.env.template`; BLE timeout/default behavior is unchanged and Thread commands remain synchronous.
- Docs describe `power-si` as a 5 second poll Thread SED and include debug evidence commands: `ot mode`, `ot pollperiod`, OTBR `child table`, and SRP service checks.

Earlier validation evidence:
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `go test ./internal/rigconfig ./internal/thread` passed.
- `just rig::test` passed across all rig packages.
- `just power-si::mcu::build` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24/zephyr/zephyr.hex`.
- `just power-si::mcu::build-debug` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- Release and debug generated `.config` files both contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, and `CONFIG_OPENTHREAD_POLL_PERIOD=5000`.
- `git diff --check` passed.
- `python3 -m pytest ...` was not run because `pytest` is not installed in the active Python environment; the explicit unittest and Go validation above were used instead.

SED hardware finding (2026-06-26):
- User-run debug evidence showed pure pre-attach SED mode (`rxOnWhenIdle=0` before Thread attach) repeatedly failed during sleepy child attach before SRP traffic was emitted. PSA/SRP key diagnostics succeeded, so SRP crypto was not the root cause.
- The Arduino PoC path that registers successfully does not set SED mode before attach; it joins in the default receiver-on posture.
- Firmware now keeps the stock Zephyr/OpenThread SED build and 5000 ms poll contract, but starts Thread in a temporary receiver-on SRP bootstrap mode, waits for `SRP update accepted`, then switches the attached child to steady-state SED mode with `mRxOnWhenIdle=false`.
- AC #2 still requires hardware evidence after this bootstrap-to-SED change: debug logs should include `Thread SRP bootstrap mode configured`, `SRP update accepted`, `Thread SED link mode configured after SRP registration`, and the current post-SRP SED transition confirmation, followed by shell/OTBR proof of `ot mode=n`, `ot pollperiod=5000`, child-table `R=0`, and SRP service `deleted:false`.

Bootstrap-to-SED validation evidence (2026-06-26):
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `go test ./internal/rigconfig ./internal/thread` passed.
- `just rig::test` passed across all rig packages.
- `just power-si::mcu::build` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24/zephyr/zephyr.hex`.
- `just power-si::mcu::build-debug` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- Release and debug generated `.config` files both contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, and `CONFIG_OPENTHREAD_POLL_PERIOD=5000`.
- Stale-doc/source grep for the previous pure-SED boot log, stale receiver-on wording, and old 8000 ms timeout wording returned no matches.
- `git diff --check` passed.
- AC #2 remains open until user-run debug hardware output shows the bootstrap attach, SRP acceptance, final `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP service `deleted:false` on port `5683`.

SED transition hardware blocker (2026-06-26):
- User-run debug evidence after the bootstrap-to-SED change showed the receiver-on SRP bootstrap path works: the device reached `role=child`, sent SRP traffic, received `SRP update accepted`, and registered `power-si._txing-coap._udp` on port `5683`.
- The same log showed the failure is after the SED switch: OpenThread changed mode `0x0d -> 0x05`, immediately dropped `role child -> detached`, then repeated rx-off child attach attempts failed with `DataPollSender: Data poll timeout`.
- This proves the remaining blocker is the current Zephyr/Silabs rx-off/data-poll path on XIAO MG24, not factory data, SRP crypto, SRP server discovery, or CoAP startup.
- Firmware now has a one-shot safety fallback: after SRP success it attempts SED, but if the device does not remain attached as a SED, it reverts to receiver-on SRP bootstrap mode for the rest of the boot so the device remains discoverable and controllable. AC #1 is reopened because that fallback intentionally permits receiver-on steady state when SED fails; AC #2 remains open until hardware can stay attached with `ot mode=n`, `ot pollperiod=5000`, child-table `R=0`, and SRP `deleted:false`.

SED fallback validation evidence (2026-06-26):
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `go test ./internal/rigconfig ./internal/thread` passed.
- `just power-si::mcu::build-debug` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- `just power-si::mcu::build` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24/zephyr/zephyr.hex`.
- Release and debug generated `.config` files both contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, and `CONFIG_OPENTHREAD_POLL_PERIOD=5000`.
- `git diff --check` passed.

SED fallback timing update (2026-06-26):
- Follow-up user-run debug evidence stopped around 30 seconds after boot. The device had already registered SRP and then failed the SED transition, but the fallback was configured to fire 30 seconds after the SED switch, which would have been roughly 46 seconds after boot in that capture.
- The fallback grace window is now 5 seconds after SED activation or SED detachment so the device should quickly revert to receiver-on bootstrap mode when the current Zephyr/Silabs SED data-poll path fails. This keeps recovery visible in normal debug logs while AC #1 and AC #2 remain open for true steady-state SED behavior.
- Validation after the timing change: `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed; `go test ./internal/rigconfig ./internal/thread` passed; `just power-si::mcu::build-debug` passed; `just power-si::mcu::build` passed; release/debug `.config` still contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, and `CONFIG_OPENTHREAD_POLL_PERIOD=5000`; `git diff --check` passed.

SED fallback hardware evidence (2026-06-26):
- User-run debug log confirmed the 5 second fallback fires. The device registered SRP, switched `Mode 0x0d -> 0x05`, dropped `Role child -> detached`, then logged `Thread SED mode did not remain attached: role=detached rxOnWhenIdle=0; reverting to SRP bootstrap mode`.
- The firmware then changed back to `Mode 0x05 -> 0x0d`, logged `Thread SRP bootstrap mode configured: rxOnWhenIdle=1 poll=5000 ms fullNetworkData=1`, and reattached as `Role detached -> child` with mode `0x0d`.
- This confirms the fallback preserves Thread attachment after SED failure, but it is not SED acceptance evidence. AC #1 and AC #2 remain open because the current hardware still does not stay attached as `ot mode=n` / child-table `R=0`.

SED hard-fault mitigation (2026-06-26):
- User-run debug evidence later showed a hard fault after fallback recovery while receiving normal MLE advertisements: `Bus fault on vector table read`, `pc=0x0000000a`, and a RAM-looking return address. That pattern is consistent with corrupted control flow or stack state rather than a normal OpenThread error return.
- At this stage firmware avoided live OpenThread link-mode flips in both directions. After SRP acceptance it disabled Thread, configured SED link mode, and re-enabled Thread. If SED did not remain attached, fallback disabled Thread, configured receiver-on SRP bootstrap mode, and re-enabled Thread. Later hardware evidence narrowed the remaining failure to rx-off reattach/data-poll handling, so this was superseded by the live-transition experiment below.
- The Zephyr system workqueue stack is explicitly raised to `4096` because the delayed SED transition/fallback work calls into OpenThread. Debug firmware also enables `CONFIG_STACK_SENTINEL=y` so any remaining stack issue should fail closer to the actual overflow.
- Validation after this mitigation: `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed; `go test ./internal/rigconfig ./internal/thread` passed; `just power-si::mcu::build-debug` passed; `just power-si::mcu::build` passed; release/debug `.config` both contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, `CONFIG_OPENTHREAD_POLL_PERIOD=5000`, and `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE=4096`; debug `.config` contains `CONFIG_STACK_SENTINEL=y`; `git diff --check` passed.

Stale debug-image evidence (2026-06-26):
- User-run debug evidence on new hardware showed SRP registration succeeded, then `Mode 0x0d -> 0x05`, `Role child -> detached`, repeated `DataPollSender: Data poll timeout`, and fallback back to receiver-on mode. Subsequent shell output reported `ot state=child`, `ot mode=rn`, and `ot pollperiod=5000`.
- That proves the device was not sleeping after fallback; `rn` is the expected receiver-on SRP bootstrap fallback mode, not TASK-21.5 SED acceptance.
- The attached log contained the old string `Thread SED mode active after SRP registration`, while the then-current rebuilt debug ELF contained `Thread SED link mode configured after SRP registration`, `Thread restarted in SED mode after SRP registration`, and `Thread restarted in SRP bootstrap mode after SED fallback`. Treat this evidence as produced by a stale pre-restart debug image. Docs now state that `just power-si::mcu::flash debug` uses the already-built HEX and does not rebuild, so the operator must rerun `just power-si::mcu::build-debug` before flashing after firmware changes.

Current debug-image SED evidence (2026-06-27):
- User-run debug evidence with the current image showed `Thread SED link mode configured after SRP registration`, `Thread restarted in SED mode after SRP registration`, then the same rx-off attach failure: `Role disabled -> detached`, `DataPollSender: Data poll timeout`, and `Thread SED mode did not remain attached`.
- Fallback then restarted Thread back into receiver-on SRP bootstrap mode and reattached as a child: `Thread restarted in SRP bootstrap mode after SED fallback`, followed by `Role detached -> child`.
- No hard fault was present in this capture through the post-fallback receiver-on advertisement stream. This supports the restart/stack mitigation, but AC #1 and AC #2 remain open because the device still does not stay in `ot mode=n` / OTBR child-table `R=0`.

SED data-poll receive-window experiment (2026-06-27):
- Local Zephyr Silabs S2 defaults force `CONFIG_OPENTHREAD_MIN_RECEIVE_ON_AFTER=0`, while OpenThread's core default is `5504 us`. The failing hardware path is rx-off attach/data-poll response handling after the SED restart, so `power-si` now restores `CONFIG_OPENTHREAD_MIN_RECEIVE_ON_AFTER=5504` in its application config.
- This is an evidence-driven firmware experiment, not acceptance proof. AC #1 and AC #2 remain open until user-run debug hardware shows the device stays attached with `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP service `deleted:false`.

SED receive-window validation evidence (2026-06-27):
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `go test ./internal/rigconfig ./internal/thread` passed.
- `just power-si::mcu::build-debug` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- `just power-si::mcu::build` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24/zephyr/zephyr.hex`.
- Release and debug generated `.config` files both contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, `CONFIG_OPENTHREAD_POLL_PERIOD=5000`, `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE=4096`, and `CONFIG_OPENTHREAD_MIN_RECEIVE_ON_AFTER=5504`; debug `.config` still contains `CONFIG_STACK_SENTINEL=y`.

SED live-transition experiment (2026-06-27):
- User-run hardware evidence after the receive-window change still showed `Mode 0x0d -> 0x05`, `Role disabled -> detached`, and `DataPollSender: Data poll timeout`, followed by fallback to receiver-on mode. OTBR then showed `R=1`, and the device shell reported `ot mode=rn`.
- The log also showed `Sent data poll, fp:yes`, which means the parent ACKed the data poll with frame-pending set but the child did not receive the following indirect frame. That keeps the blocker in the rx-off data-poll path, not SRP or factory provisioning.
- Firmware now changes the already-attached, SRP-registered child to SED with a live `otThreadSetLinkMode()` update instead of disabling Thread and forcing a fresh rx-off child attach. The receiver-on fallback remains in place if the live mode update still drops attachment.

SED live-transition validation evidence (2026-06-27):
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `go test ./internal/rigconfig ./internal/thread` passed.
- `just power-si::mcu::build-debug` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- `just power-si::mcu::build` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24/zephyr/zephyr.hex`.
- Release and debug generated `.config` files still contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, `CONFIG_OPENTHREAD_POLL_PERIOD=5000`, `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE=4096`, and `CONFIG_OPENTHREAD_MIN_RECEIVE_ON_AFTER=5504`; debug `.config` still contains `CONFIG_STACK_SENTINEL=y`.

Live-transition hardware blocker confirmation (2026-06-27):
- User-run debug evidence with the current live-transition image confirmed SRP registration succeeds in receiver-on bootstrap mode: `SRP update accepted` and service `power-si._txing-coap._udp` reaches `Registered` on port `5683`.
- The live SED transition still fails immediately after `Mode 0x0d -> 0x05`: OpenThread logs `Role child -> detached`, then rx-off child attach reaches `ChildIdReq` and repeatedly logs `Sent data poll, fp:yes` followed by `DataPollSender: Data poll timeout`.
- The `fp:yes` ACK proves the parent has indirect data queued for the child; the missing follow-up frame keeps the remaining blocker in the MG24/Zephyr/Silabs rx-off data-poll receive path rather than Thread dataset, SRP service configuration, PSA/SRP key handling, or rig/OTBR discovery.
- The safety fallback still works: firmware reverts to receiver-on bootstrap mode, reattaches, and shell evidence reports `ot state=child`, `ot mode=rn`, and `ot pollperiod=5000`. This is operationally useful, but it is not SED acceptance; AC #1 and AC #2 remain open.

Test-only Zephyr patch path (2026-06-27):
- Stock Zephyr remains the default and production build path. A local test patch was added at `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` only to test the suspected Silabs driver rx-off data-poll receive bug.
- The patch adds an explicit background RX restart after a MAC data poll ACK with frame-pending set in `drivers/ieee802154/ieee802154_silabs_efr32.c`.
- The shared MCU build script applies this patch only when `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1` is set, and reverses it after the build so the local Zephyr checkout returns to stock. This is hardware-debug evidence gathering, not acceptance of a Zephyr fork or product dependency.
- AC #1 and AC #2 remain open until user-run hardware evidence from the test image shows whether `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP `deleted:false` can hold in steady state.

Test-only Zephyr patch validation evidence (2026-06-27):
- `git -C devices/common/mcu/zephyr/zephyr apply --check devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed.
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed: 3 tests.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and built `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- The patched build log showed the test patch was applied before `west build` and reversed after link/image generation. `git -C devices/common/mcu/zephyr/zephyr status --short` was clean afterward, and the patch still passed `git apply --check`, confirming the local Zephyr checkout returned to stock.

First test-only Zephyr patch hardware result (2026-06-27):
- User-run hardware evidence with the test-patched debug image still failed TASK-21.5 SED acceptance. The device registered SRP in receiver-on bootstrap mode, switched `Mode 0x0d -> 0x05`, detached, sent sleepy data polls, and still logged repeated `Sent data poll, fp:yes` followed by `DataPollSender: Data poll timeout`.
- The fallback reattached in receiver-on mode. Shell evidence reported `ot state=child`, `ot mode=rn`, and `ot pollperiod=5000`; OTBR child table showed `R=1`, `D=0`, `N=1`, and SRP service `power-si._txing-coap._udp.default.service.arpa` remained `deleted:false`.
- This proves the first patch, which only called `sl_rail_start_rx()` after a frame-pending data-poll ACK, is insufficient. The test patch now forces an idle-abort before restarting RX and logs `IEEE802154 test: data-poll fp=1 rx restart ...` with before/after RAIL state and return codes so the next hardware run can distinguish "RX was not actually restarted" from "RX restarted but the indirect frame is still not received."

Second test-only Zephyr patch validation evidence (2026-06-27):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` to call `sl_rail_idle(..., SL_RAIL_IDLE_ABORT, true)` before restarting RX after a data-poll ACK with frame-pending. The patch now logs `IEEE802154 test: data-poll fp=1 rx restart before=... idle=... start=... after=...`.
- `git -C devices/common/mcu/zephyr/zephyr apply --check devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed.
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed: 3 tests.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- `rg -a "IEEE802154 test: data-poll fp=1" devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.elf` found the expected log string in the rebuilt image. `git -C devices/common/mcu/zephyr/zephyr status --short` was clean afterward, confirming the local Zephyr checkout returned to stock.

Second test-only Zephyr patch hardware result (2026-06-27):
- User-run debug evidence with the stronger test patch again failed TASK-21.5 SED acceptance, but the failing path changed. Receiver-on bootstrap still attached and registered SRP successfully, then live SED transition changed `Mode 0x0d -> 0x05`, dropped `Role child -> detached`, and entered rx-off attach.
- In this run the first rx-off attach reached `ChildIdReq` but the Child ID Request hit a full 16-attempt MAC `NoAck` burst before any `Sent data poll, fp:yes` event appeared. Therefore the data-poll frame-pending restart hook did not execute, and the absence of the `IEEE802154 test: data-poll fp=1 rx restart ...` line is expected for this capture.
- The same capture showed weak parent RSSI around `-84` to `-89 dBm`; physical link margin should be controlled in the next hardware run before drawing conclusions from a `NoAck` result.
- The fallback still worked: firmware reverted to receiver-on SRP bootstrap mode, restarted Thread, and eventually reattached as `Role detached -> child` with saved mode `0x0d`. AC #1 and AC #2 remain open.

Third test-only Zephyr patch diagnostic update (2026-06-27):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` again to keep the data-poll frame-pending RX restart experiment and also log ACK-requested TX state. The patch now emits `IEEE802154 test: ack-tx start ...`, `ack-timeout ...`, and `ack-failed ...` lines with frame type, sequence, RAIL radio state, and pending-data flag.
- This remains opt-in hardware diagnostics only. Stock Zephyr remains the default and production build path, and the local Zephyr checkout must be clean after every patched build.

Third test-only Zephyr patch validation evidence (2026-06-27):
- `git -C devices/common/mcu/zephyr/zephyr apply --check devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed.
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed: 3 tests.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- `rg -a "IEEE802154 test: (ack-tx|data-poll fp=1)" devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.elf` found both diagnostic strings. `git -C devices/common/mcu/zephyr/zephyr status --short` was clean afterward, confirming the local Zephyr checkout returned to stock.

Third test-only Zephyr patch hardware result (2026-06-27):
- User-run hardware evidence with `ack-tx` diagnostics confirmed the simple RX-restart hypothesis is false. During rx-off attach, the Child ID Request was sent, the subsequent MAC Data Request was ACKed with `frame_pending=1`, and the test patch logged `data-poll fp=1 rx restart before=0x2 idle=0 start=0 after=0x2` repeatedly.
- Even with successful idle-abort and RX restart, OpenThread still logged repeated `DataPollSender: Data poll timeout`, then fallback returned the device to receiver-on bootstrap mode. This keeps TASK-21.5 AC #1 and AC #2 open.
- The remaining unknown is whether the parent's indirect frame never reaches the MG24 radio after the `fp=1` ACK, or whether RAIL/driver receives it and then rejects or drops it before OpenThread sees it.

Fourth test-only Zephyr patch diagnostic update (2026-06-27):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` to add pending-indirect RX diagnostics while `em_pending_data` is true. The patch now logs `IEEE802154 test: pending-rx ...` at packet-info, packet-details, validation, copy, parsed-frame, and net-delivery points.
- The next hardware capture should answer whether any RAIL `RX_PACKET_RECEIVED` event arrives after `data-poll fp=1 rx restart ...`. No `pending-rx` lines after `fp=1` means the indirect frame is not reaching the driver; `pending-rx invalid`, `copy-failed`, or negative `pending-rx net result` would move the blocker to validation/copy/net delivery.

Fourth test-only Zephyr patch validation evidence (2026-06-27):
- `git -C devices/common/mcu/zephyr/zephyr apply --check devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- `rg -a "IEEE802154 test: (ack-tx|data-poll fp=1|pending-rx)" devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.elf` found all diagnostic strings.
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py`, and `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` all passed. `git -C devices/common/mcu/zephyr/zephyr status --short` was clean afterward, confirming the local Zephyr checkout returned to stock.

Fourth test-only Zephyr patch hardware result (2026-06-27):
- User-run hardware evidence with pending-RX diagnostics showed SRP still registers before the SED transition: `SRP update accepted`, host/service state `Registered`, and service `power-si._txing-coap._udp` on port `5683`.
- After the live SED transition, rx-off attach reached `ChildIdReq` and data polls received ACKs with `frame_pending=1`. The driver logged successful RX restarts, but the `pending-rx` packets during the OpenThread data-poll window were only ACK frames (`type=2`, `len=5`, `fp=1`), followed by `DataPollSender: Data poll timeout`.
- A later pending data frame was received and passed to the net stack only after fallback began (`pending-rx parsed type=1 ... copied=117`, `pending-rx net result=0`). That rules out a simple net-stack rejection and points to timing or delayed indirect delivery after the stock 100 ms data-poll response window.

Fifth test-only Zephyr patch diagnostic update (2026-06-27):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` to keep the existing Silabs rx-off ACK/TX and pending-RX diagnostics, and also widen `OPENTHREAD_CONFIG_MAC_DATA_POLL_TIMEOUT` from the stock `100 ms` to `1000 ms`.
- This remains opt-in hardware diagnostics only through `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr remains the default production path. The next hardware run should show whether the indirect Child ID Response arrives before the widened timeout while the device is still in SED mode.

Fifth test-only Zephyr patch validation evidence (2026-06-27):
- `git -C devices/common/mcu/zephyr/zephyr apply --check devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- The patched build log showed the patch was applied before `west build` and reversed after image generation; `git -C devices/common/mcu/zephyr/zephyr status --short` was clean afterward.
- `rg -a "IEEE802154 test: (ack-tx|data-poll fp=1|pending-rx)" devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.elf` found all diagnostic strings.
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory`, and `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` all passed. `git diff --check` passed.

Fifth test-only Zephyr patch server-side result (2026-06-27):
- User-run OTBR evidence after flashing the 1000 ms timeout test image showed `power-si._txing-coap._udp.default.service.arpa` remained registered with `deleted:false`, port `5683`, TXT `type=power-si`, and the expected mesh-local address.
- The same OTBR child table showed `R=1`, `D=0`, `N=1` for extended MAC `5a68b0786a487e55`. This means the device was still attached as receiver-on, not as the intended sleepy child, so AC #1 and AC #2 remain open.
- UART evidence is still needed for this test image to decide whether the widened timeout let the indirect response arrive during SED attach before fallback, or whether the same delayed/absent data-poll response behavior remained unchanged.

Fifth test-only Zephyr patch UART result (2026-06-27):
- User-run UART evidence showed the `1000 ms` data-poll timeout changed behavior but still did not produce SED acceptance. After `Mode 0x0d -> 0x05`, the SED attach reached `ChildIdReq`, sent a data poll with `fp:yes`, then left `ChildIdReq` roughly one second later without receiving the indirect response in SED mode.
- The app fallback fired at about five seconds after the SED switch, before the second SED attach attempt could complete. A pending non-ACK data frame was then delivered only after fallback began and receiver-on bootstrap mode was restored.
- This suggests two separate issues for the next diagnostic: the data-poll response can still arrive later than `1000 ms`, and the app fallback grace period is too short to observe more than one SED attach attempt.

Sixth test-only SED diagnostic update (2026-06-27):
- Increased the app SED fallback grace window from `5` seconds to `20` seconds so the device can make multiple rx-off attach attempts before the operational receiver-on fallback takes over.
- Updated the opt-in Zephyr test patch to widen `OPENTHREAD_CONFIG_MAC_DATA_POLL_TIMEOUT` from the stock `100 ms` to `2500 ms`. This remains a hardware diagnostic only through `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; normal builds continue to use stock Zephyr without the local patch.
- The next hardware run should show whether the indirect Child ID Response arrives before `2500 ms` while still in SED mode, or whether SED attach continues to fail across multiple attempts even with the longer timeout and grace window.

Sixth test-only SED diagnostic validation evidence (2026-06-27):
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory`, and `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` all passed.
- `git -C devices/common/mcu/zephyr/zephyr apply --check devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `just power-si::mcu::build-debug` passed with the stock Zephyr tree and rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and rebuilt the diagnostic debug HEX. The build applied the test patch before `west build` and reversed it afterward; `git -C devices/common/mcu/zephyr/zephyr status --short` was clean.
- `just power-si::mcu::build` passed and rebuilt the release HEX. Release and debug `.config` files both contain `CONFIG_OPENTHREAD_MTD=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, `CONFIG_OPENTHREAD_POLL_PERIOD=5000`, `CONFIG_OPENTHREAD_MIN_RECEIVE_ON_AFTER=5504`, and `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE=4096`.
- `rg -a "IEEE802154 test: (ack-tx|data-poll fp=1|pending-rx)" devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.elf` found all diagnostic strings in the patched debug image. `git diff --check` passed.

Sixth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence with the `2500 ms` MAC data-poll timeout and `20` second app fallback showed receiver-on bootstrap still succeeds: the device attaches, registers SRP, and receives `SRP update accepted`.
- The live SED transition then changes `Mode 0x0d -> 0x05`, detaches, and makes multiple rx-off attach attempts before fallback. During those attempts the Silabs driver receives and delivers non-ACK Parent Response frames while SED mode is active, including `pending-rx parsed type=1 ... copied=117` followed by OpenThread `Receive Parent Response`. This proves the driver/net path can deliver at least some non-ACK frames in SED mode.
- The attach still fails in `ChildIdReq`. The `ChildIdReq -> Idle` transition happens roughly `1250 ms` after sending the Child ID Request, which matches OpenThread's stock MLE `kChildIdResponseTimeout`, so the widened `2500 ms` MAC data-poll timeout is not the only limiting timer.
- Fallback then restores receiver-on bootstrap mode and reattaches successfully. AC #1 and AC #2 remain open because the device still does not stay attached as `ot mode=n` / OTBR child-table `R=0`.

Seventh test-only SED diagnostic update (2026-06-28):
- Kept the default production path on stock Zephyr/OpenThread. The opt-in diagnostic path now applies two temporary patches when `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1` is set: the existing Zephyr Silabs driver/config patch and a new OpenThread-module patch.
- The new OpenThread-module diagnostic patch widens MLE `kChildIdResponseTimeout` from stock `1250 ms` to `5000 ms` and logs the MLE Child ID Response wait plus the MAC indirect-data wait. This should test whether the indirect Child ID Response can arrive after the stock MLE timeout while the device is still in SED mode.
- The MCU helper now checks, applies, reverses, and verifies the Zephyr and OpenThread checkouts independently so interrupted diagnostic builds cannot silently leave either checkout dirty.

Seventh test-only SED diagnostic validation evidence (2026-06-28):
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed.
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed: 3 tests.
- `git -C devices/common/mcu/zephyr/zephyr apply --check /Users/Maxim/Developer/txing/devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `git -C devices/common/mcu/zephyr/modules/lib/openthread apply --check /Users/Maxim/Developer/txing/devices/common/mcu/patches/openthread-sed-child-id-timeout-test.patch` passed.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and rebuilt the diagnostic debug HEX. The build applied both test patches before `west build` and reversed both afterward; `git -C devices/common/mcu/zephyr/zephyr status --short` and `git -C devices/common/mcu/zephyr/modules/lib/openthread status --short` were clean afterward.
- `rg -a "IEEE802154 test: (ack-tx|data-poll fp=1|pending-rx)|txing SED test: (Child ID Response timeout|waiting for indirect data timeout)" devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.elf` found the expected diagnostic strings.
- `git diff --check` passed.

Seventh test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence with the `5000 ms` MLE Child ID Response wait confirmed receiver-on bootstrap still succeeds: the device attaches, sends SRP, receives `SRP update accepted`, and registers `power-si._txing-coap._udp` on port `5683`.
- The live SED transition still changes `Mode 0x0d -> 0x05`, drops the child role, and fails rx-off child attach even though OpenThread now waits the full `5000 ms` in `ChildIdReq`. The blocker is no longer only the stock `1250 ms` MLE timeout.
- During SED attach the parent ACKs data polls with `fp:yes`. Some attempts only receive ACK frames before timeout; later attempts receive a non-ACK pending data frame (`type=1`, `len=69`, `sec=0`) and deliver it to the net stack with `pending-rx net result=0`, but OpenThread does not log `Receive Child ID Response`.
- Receiver-on fallback then succeeds and receives the real Child ID Response immediately as a larger secure MLE frame (`IPv6 UDP len:206`, `sec:yes`). The remaining unknown is whether the `len=69 sec=0` SED pending frame is unrelated traffic, malformed for the expected MLE exchange, or a driver/6LoWPAN delivery artifact.

Eighth test-only SED diagnostic update (2026-06-28):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` to log a bounded hex dump of the first 32 copied bytes for pending-RX frames while `em_pending_data` is true. The new marker is `IEEE802154 test: pending-rx bytes[0..31]`.
- The next hardware run should capture those hex-dump lines around the `len=69 sec=0` SED pending frames. That should identify whether the frame is the expected Thread/MLE Child ID Response path, an unrelated MLE/6LoWPAN frame, or data that needs a deeper Silabs/OpenThread boundary debug.

Eighth test-only SED diagnostic validation evidence (2026-06-28):
- `git -C devices/common/mcu/zephyr/zephyr apply --check /Users/Maxim/Developer/txing/devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `git -C devices/common/mcu/zephyr/modules/lib/openthread apply --check /Users/Maxim/Developer/txing/devices/common/mcu/patches/openthread-sed-child-id-timeout-test.patch` passed.
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed.
- `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 9 tests.
- `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed: 3 tests.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and rebuilt the diagnostic debug HEX. The build applied both test patches before `west build` and reversed both afterward.
- `rg -a "pending-rx bytes|txing SED test: Child ID Response timeout|waiting for indirect data timeout" devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.elf` found the expected diagnostic strings in the rebuilt image.
- `git -C devices/common/mcu/zephyr/zephyr status --short`, `git -C devices/common/mcu/zephyr/modules/lib/openthread status --short`, and `git diff --check` were clean.

Eighth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence with frame-prefix dumps confirmed SRP still registers in receiver-on bootstrap mode, then the live SED transition still fails in rx-off `ChildIdReq` despite the `5000 ms` MLE wait and `2500 ms` MAC data-poll wait.
- The `len=69 sec=0` frame is not the expected Child ID Response. Its MAC prefix starts `41 d8 ... 69 d2 ff ff`, which decodes as an unsecure data frame addressed to the Thread PAN with short destination `0xffff` (broadcast). OpenThread does not log `Receive Child ID Response` after this frame.
- The `len=117 sec=0` frames start `61 dc ...` and are unsecure Parent Responses addressed directly to the child extended address; OpenThread logs `Receive Parent Response` for them. These frames prove SED-mode RX delivery works for some frames, but they are not the secured Child ID Response.
- Receiver-on fallback still receives the actual Child ID Response immediately as a larger secure frame (`IPv6 UDP len:206`, `sec:yes`) and reattaches. AC #1 and AC #2 remain open.

Ninth test-only SED diagnostic update (2026-06-28):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` to keep the pending data-poll RX window open across unsecure pending-window frames. The test patch now logs `pending-rx ... keep-rx` for unsecure frames and only ends the pending receive window on a secured frame with `pending-rx ... end-on-secured`.
- This tests a concrete Silabs driver hypothesis: the stock driver clears `em_pending_data` and yields the radio on the first non-ACK data frame after a frame-pending data-poll ACK. In the hardware log, that first non-ACK frame can be an unrelated unsecure broadcast, so the driver may stop RX before the secured indirect Child ID Response can arrive.
- This remains opt-in diagnostics only through `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr/OpenThread remains the default production path.

Ninth test-only SED diagnostic validation evidence (2026-06-28):
- `git -C devices/common/mcu/zephyr/zephyr apply --check /Users/Maxim/Developer/txing/devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` passed.
- `git -C devices/common/mcu/zephyr/modules/lib/openthread apply --check /Users/Maxim/Developer/txing/devices/common/mcu/patches/openthread-sed-child-id-timeout-test.patch` passed.
- `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and rebuilt the diagnostic debug HEX. The build applied both test patches before `west build` and reversed both afterward.
- `rg -a "pending-rx .*keep-rx|pending-rx .*end-on-secured|pending-rx bytes|Child ID Response timeout" devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.elf` found the expected diagnostic strings in the rebuilt image.
- `git -C devices/common/mcu/zephyr/zephyr status --short` and `git -C devices/common/mcu/zephyr/modules/lib/openthread status --short` were clean afterward.
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory`, and `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` all passed.

Ninth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence with the keep-RX diagnostic active confirmed receiver-on SRP bootstrap still works: SRP reached Registered and the service stayed on port 5683 before the SED transition.
- After Mode 0x0d -> 0x05, OpenThread still forced Role child -> detached and entered rx-off child attach. During the attach attempts, the Zephyr/Silabs diagnostic kept RX open across unsecure pending-window frames and logged keep-rx for unsecure Parent Response or broadcast frames, but no secured Child ID Response arrived while the device remained in SED attach.
- Receiver-on fallback later received the secured Child ID Response immediately and reattached. This rules out the previous hypothesis that the first unsecure pending frame merely closed the RX window before the secured indirect response. AC #1 and AC #2 remain open.

Tenth test-only SED diagnostic update (2026-06-28):
- The opt-in OpenThread diagnostic patch now also suppresses the rx-on to sleepy reattach decision in Mle::SetDeviceMode and logs: txing SED test: suppressing rx-on to sleepy reattach; sending child update in place.
- This tests whether the already-attached, SRP-registered child can move to rx-off mode through the normal Child Update path without entering the failing rx-off Child ID reattach sequence. This is diagnostics only under TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1; stock Zephyr/OpenThread remains the default production path.
- Next hardware evidence should check for that log marker, absence of Role child -> detached immediately after Mode 0x0d -> 0x05, shell ot mode=n, ot pollperiod=5000, OTBR child-table R=0, and SRP service deleted:false on port 5683.

Tenth test-only SED diagnostic validation evidence (2026-06-28):
- git apply --check passed for both devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch against the Zephyr checkout and devices/common/mcu/patches/openthread-sed-child-id-timeout-test.patch against the OpenThread checkout.
- TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug passed and rebuilt devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex. The build applied both test patches before west build and reversed both afterward; both nested checkouts were clean afterward.
- The rebuilt debug ELF contains the new suppressing rx-on to sleepy reattach marker plus the previous pending-rx keep-rx/end-on-secured, Child ID Response timeout, and indirect data wait markers.
- python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py passed; python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory passed; devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py passed; git diff --check passed.

Tenth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence confirmed the suppress-reattach OpenThread diagnostic fired after SRP registration: Mode 0x0d -> 0x05 was followed by txing SED test: suppressing rx-on to sleepy reattach; sending child update in place, not by an immediate Role child -> detached.
- The device sent in-place Child Update Requests while advertising rx-on:no, but because the radio was already rx-off, the parent response still had to come through the sleepy indirect/data-poll path. Data polls were ACKed with frame_pending=1, but the expected Child Update Response was not delivered before OpenThread later detached at about 8.6 seconds.
- This narrows the blocker from rx-off Child ID attach specifically to the general sleepy indirect receive path used by both Child Update Response and Child ID Response. Receiver-on fallback still recovered and later received the secured Child ID Response immediately.

Eleventh test-only SED diagnostic update (2026-06-28):
- Updated the opt-in OpenThread diagnostic patch to hold MeshForwarder RX on only during the post-SRP rx-on -> sleepy Child Update transition while still advertising the desired rx-off mode in the Child Update Request.
- The patch logs txing SED test: holding rx-on for sleepy Child Update response when it keeps RX on for that transition, and txing SED test: releasing rx-on hold after sleepy Child Update response when the parent acknowledges the mode update and the child is released into rx-off SED mode.
- This tests whether steady-state SED can work after the parent accepts the child mode change, separating the transition-response problem from normal sleepy operation. This remains diagnostic only under TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1; stock Zephyr/OpenThread remains the default production path.
- Next hardware evidence should check for the hold and release markers, no fallback log, shell ot mode=n, ot pollperiod=5000, OTBR child-table R=0, and SRP service deleted:false on port 5683.

Eleventh test-only SED diagnostic validation evidence (2026-06-28):
- git apply --check passed for both test patches.
- TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug passed and rebuilt devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex. The build applied both test patches before west build and reversed both afterward; both nested checkouts were clean afterward.
- The rebuilt debug ELF contains the new holding rx-on for sleepy Child Update response and releasing rx-on hold after sleepy Child Update response markers, plus the existing suppress-reattach and pending-RX markers.
- python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py passed; python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory passed; devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py passed.

Eleventh test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence with the RX-hold diagnostic confirmed the latest test image was flashed: after SRP reached `SRP update accepted`, the SED transition logged `Mode 0x0d -> 0x05`, `txing SED test: holding rx-on for sleepy Child Update response`, and `Thread switched to SED mode after SRP registration`.
- The matching `txing SED test: releasing rx-on hold after sleepy Child Update response` marker was not present. Instead, repeated in-place Child Update Requests saw heavy MAC `NoAck` retries, the child later detached, and the app fallback logged `Thread SED mode did not remain attached: role=detached rxOnWhenIdle=0; reverting to SRP bootstrap mode`.
- This means the RX-hold diagnostic did not produce TASK-21.5 acceptance. The result is also noisy because receiver-on bootstrap and the SED transition both show poor unicast reliability to the parent, with RSSI around -81 to -83 dBm and many `NoAck` retries. A clean retest should be done with the device close to the OTBR or otherwise improved link quality before treating this as proof that RX-hold cannot work.
- Next hardware evidence should capture device `ot counters mac`, `ot counters mle`, `ot parent`, `ot state`, `ot mode`, and OTBR `child table`/`neighbor table` around the SED switch. Acceptance remains open until the release marker appears, no fallback fires, `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP remains `deleted:false` on port `5683`.

Post-fallback counter evidence (2026-06-28):
- User-run device and OTBR counters after the RX-hold diagnostic ended show the device in receiver-on fallback, not accepted SED: device shell reported `ot state=child`, `ot mode=rn`; OTBR child table reported `R=1,D=0,N=1`; SRP remained registered as `deleted:false` on port `5683`.
- MLE counters recorded repeated attachment churn (`Attach Attempts: 7`, `Role Detached: 3`, `Role Child: 2`, `Time Detached Milli: 36642`), matching the UART log where the SED transition failed and fallback restored the working receiver-on child state.
- MAC counters after recovery showed the final link is usable but marginal (`TxAcked: 15` of `TxAckRequested: 16`, `TxRetry: 54`, `TxDirectMaxRetryExpiry: 1`; OTBR neighbor RSSI about -85/-81 dBm and LQI 2). This supports retesting closer to the OTBR, but the current evidence still confirms AC #2 is not met because the accepted child remains `R=1` rather than `R=0`.
- For the next run, reset counters immediately before reboot or before the SED switch, then capture counters immediately after the hold/release or fallback markers so the transition traffic is isolated from the recovered receiver-on state.

Temporary +8 dBm TX-power diagnostic update (2026-06-28):
- Added a debug-only `power-si` Kconfig radio TX-power override. `devices/power-si/mcu/zephyr/debug.conf` enables `CONFIG_TXING_POWER_SI_TEST_TX_POWER_OVERRIDE=y` and `CONFIG_TXING_POWER_SI_TEST_TX_POWER_DBM=8`; production `prj.conf` leaves the override disabled.
- The app applies the override through Zephyr's `ieee802154_radio_api.set_txpower` callback for the board's `zephyr,ieee802154` radio and logs either `Thread radio TX power override active: 8 dBm` or the reason it was skipped/failed. This is not a production radio policy; it is only to rule out link-margin effects while TASK-21.5 SED diagnostics continue.
- Validation: `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed; `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed; `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed; `just power-si::mcu::build` passed; `just power-si::mcu::build-debug` passed; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` passed and reversed both temporary patches afterward.
- Generated config check: release `.config` has `# CONFIG_TXING_POWER_SI_TEST_TX_POWER_OVERRIDE is not set`; debug `.config` has `CONFIG_TXING_POWER_SI_TEST_TX_POWER_OVERRIDE=y` and `CONFIG_TXING_POWER_SI_TEST_TX_POWER_DBM=8`. The patched diagnostic debug ELF contains the TX-power marker and the RX-hold/release markers.
- Next hardware run should confirm the boot log contains `Thread radio TX power override active: 8 dBm`; then compare SED transition behavior and post-run MAC counters against the previous weak-link/no-override run.

+8 dBm SED diagnostic hardware result (2026-06-28):
- User-run UART evidence confirmed the debug TX-power override was active: `Thread radio TX power override active: 8 dBm`. RSSI improved to about -73 to -76 dBm, and receiver-on bootstrap remained fast: the device attached, registered SRP, and logged `SRP update accepted`.
- The post-SRP SED transition still failed. The log showed `Mode 0x0d -> 0x05`, the suppress-reattach and RX-hold diagnostics, and repeated `txing SED test: holding rx-on for sleepy Child Update response`, but it never logged `txing SED test: releasing rx-on hold after sleepy Child Update response`. The child detached at about 8.8 seconds and fallback fired at about 24.8 seconds.
- During rx-off attach attempts, Parent Responses were received and delivered correctly, but Child ID Responses were not received while the device stayed in SED mode. Data-poll ACKs still reported `fp:yes`; the only non-ACK pending frames received before timeout were the same unsecure 69-byte broadcast-like frames or Parent Responses. After fallback restored receiver-on bootstrap mode, the secured Child ID Response arrived immediately and the device reattached as `mode:0x0d`.
- This rules out simple link margin as the primary TASK-21.5 blocker. The remaining failure is still specific to the rx-off/Sleepy End Device indirect-response path or the mode-change Child Update response path, not SRP, factory data, PSA, or basic RF reachability.

Twelfth test-only SED diagnostic update (2026-06-28):
- The +8 dBm hardware evidence showed the RX-hold transition still failed with stronger link margin. That run also showed the previous diagnostic held MeshForwarder RX on during the post-SRP sleepy Child Update, but did not keep OpenThread's data-poll attach path active in that same hold branch.
- Updated `devices/common/mcu/patches/openthread-sed-child-id-timeout-test.patch` so the opt-in diagnostic now logs `txing SED test: holding rx-on and polling for sleepy Child Update response`, keeps MeshForwarder RX on, and also enables `DataPollSender` attach mode while waiting for the mode-change Child Update Response. This tests whether the parent queues the response as indirect data once the child advertises `rx-on:no`.
- This is still diagnostic-only under `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`. Production/default firmware continues to build from stock Zephyr/OpenThread and still leaves the local Zephyr/OpenThread checkouts clean after a diagnostic build.
- Validation passed: both test patches passed `git apply --check`; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both patches afterward; both nested Zephyr/OpenThread checkouts were clean; the debug ELF contains the new hold-and-poll marker, the release marker, the +8 dBm TX-power marker, pending-RX markers, and the widened Child ID Response timeout marker. `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory`, `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py`, and `git diff --check` passed.
- Next hardware run should confirm the new hold-and-poll marker appears after `Mode 0x0d -> 0x05`, then check for `txing SED test: releasing rx-on hold after sleepy Child Update response`. Acceptance still requires no fallback log, device shell `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP service `power-si._txing-coap._udp.default.service.arpa` remaining `deleted:false` on port `5683`.

Twelfth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence confirmed the hold-and-poll test image was flashed: after SRP registration, the SED transition logged `Mode 0x0d -> 0x05`, `txing SED test: suppressing rx-on to sleepy reattach; sending child update in place`, and `txing SED test: holding rx-on and polling for sleepy Child Update response`.
- The expected release marker never appeared. The child sent repeated in-place Child Update Requests, received only an MLE Advertisement during that transition, then detached around 8.6 seconds and entered rx-off attach. This shows holding RX-on does not yield a direct Child Update Response.
- The run also revealed that the "hold and poll" diagnostic did not actually send data polls during the hold window. OpenThread's `MeshForwarder::SetRxOnWhenIdle(true)` stops `DataPollSender`, and `DataPollSender::SendDataPoll()` rejects polling while the MAC is RX-on. Therefore this run is valid evidence that RX-on hold does not receive a direct mode-change response, but it is not evidence that RX-on plus indirect polling can work.
- After detach, rx-off attach still failed despite detailed data-poll evidence: data poll ACKs repeatedly reported `fp:yes`, the driver restarted RX and sometimes kept RX open across unsecure frames, but no secured Child ID Response arrived before the app fallback fired.
- After fallback restored receiver-on bootstrap mode (`Mode 0x05 -> 0x0d`), the next attach immediately received the secured Child ID Response and reattached as child with `mode:0x0d`. The Arduino reference sketch in `tmp/ot_ping/ot_ping.ino` also does not configure SED mode; it joins as the default receiver-on child, so it proves the physical Thread/SRP path but not sleepy behavior. AC #1 and AC #2 remain open.

Thirteenth test-only SED diagnostic update (2026-06-28):
- Updated `devices/common/mcu/patches/openthread-sed-child-id-timeout-test.patch` again so the transition diagnostic no longer holds RX on. It now logs `txing SED test: forcing immediate data poll for sleepy Child Update response`, sets MeshForwarder into rx-off mode, enables `DataPollSender` attach mode, and explicitly calls `SendDataPoll()` after the post-SRP sleepy Child Update Request. If the response arrives, it logs `txing SED test: stopping transition poll after sleepy Child Update response`.
- This directly tests the indirect-response path for the in-place Child Update, with the same detailed Silabs pending-RX logging used for Child ID attach. It remains opt-in diagnostics only under `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr/OpenThread remains the production/default source path.
- Validation passed: both test patches passed `git apply --check`; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both patches afterward; both nested checkouts were clean; the debug ELF contains the new forced-poll marker, stopping-transition-poll marker, +8 dBm marker, pending-RX markers, and widened Child ID Response timeout marker. `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory`, `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py`, and `git diff --check` passed.
- Next hardware run should confirm `txing SED test: forcing immediate data poll for sleepy Child Update response` appears after `Mode 0x0d -> 0x05`, then inspect whether a `Sent data poll, fp:yes` is followed by a secured pending frame and `Receive Child Update Response`. Acceptance still requires no fallback, device shell `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP service `power-si._txing-coap._udp.default.service.arpa` remaining `deleted:false` on port `5683`.

Thirteenth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence with the forced-poll diagnostic confirmed receiver-on SRP bootstrap still works at +8 dBm: the device attached, registered SRP, and logged `SRP update accepted`.
- The in-place SED transition still failed. After `Mode 0x0d -> 0x05`, OpenThread logged `txing SED test: suppressing rx-on to sleepy reattach; sending child update in place` and `txing SED test: forcing immediate data poll for sleepy Child Update response`, but no `Receive Child Update Response` arrived before the child detached.
- The log showed the forced data poll could transmit before the queued Child Update Request actually reached the air. Later data polls did receive ACKs with `fp:yes` and the Silabs patch restarted RX for the indirect window, but no secured pending Child Update Response or Child ID Response arrived while the device remained in SED mode. After receiver-on fallback, the secured Child ID Response arrived immediately and the device reattached as `mode:0x0d`.
- This keeps AC #1 and AC #2 open. The forced-poll test is useful evidence that the failure remains in the sleepy indirect-response path, but it also introduced a timing artifact that should be removed before the next hardware run.

Fourteenth test-only SED diagnostic update (2026-06-28):
- Updated `devices/common/mcu/patches/openthread-sed-child-id-timeout-test.patch` so the opt-in transition diagnostic no longer calls `SendDataPoll()` immediately from `SendChildUpdateRequestToParent()`. It now logs `txing SED test: scheduling attach-mode polls for sleepy Child Update response`, puts MeshForwarder into rx-off mode, enables OpenThread `DataPollSender` attach mode, and schedules bounded fast polls through the normal poll timer. If the response arrives, it logs `txing SED test: stopping transition polls after sleepy Child Update response` and stops the fast-poll user.
- This removes the out-of-order immediate-poll artifact while still testing the same indirect Child Update Response path. It remains diagnostic-only under `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr/OpenThread remains the default production path.
- Validation passed: both test patches passed `git apply --check`; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both patches afterward; both nested Zephyr/OpenThread checkouts were clean; the debug ELF contains the new scheduling/stopping poll markers, the +8 dBm marker, pending-RX markers, and widened Child ID Response timeout marker. `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory`, `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py`, and `git diff --check` passed.
- Next hardware run should confirm the new `scheduling attach-mode polls` marker appears after `Mode 0x0d -> 0x05`, then inspect whether a subsequent `Sent data poll, fp:yes` is followed by a secured pending frame and `Receive Child Update Response`. Acceptance still requires no fallback, device shell `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP service `power-si._txing-coap._udp.default.service.arpa` remaining `deleted:false` on port `5683`.

Fourteenth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence confirmed the scheduled-poll diagnostic was flashed. The device reached receiver-on SRP bootstrap, logged `SRP update accepted`, and the OTBR SRP service stayed `deleted:false` on port `5683`.
- The post-SRP SED transition still failed. After `Mode 0x0d -> 0x05`, the log showed `txing SED test: scheduling attach-mode polls for sleepy Child Update response`, data-poll ACKs with `fp:yes`, and repeated `Data poll timeout`. No `Receive Child Update Response` arrived before `Role child -> detached`.
- Rx-off attach attempts again received Parent Responses and unsecure broadcast-like frames, but not secured Child ID Responses. After fallback restored receiver-on bootstrap (`Mode 0x05 -> 0x0d`), the next Child ID Request saw `fp=1` and immediately received the secured 126-byte Child ID Response, then reattached as `mode:0x0d`.
- This keeps AC #1 and AC #2 open. The SRP service output is operationally good, but it reflects receiver-on fallback, not accepted SED steady state.

Fifteenth test-only SED diagnostic update (2026-06-28):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` so the data-poll ACK path no longer aborts and restarts RX when RAIL already reports RX state after a frame-pending data-poll ACK. It now logs `IEEE802154 test: data-poll fp=1 keep existing RX state rail=...` in that case, and only falls back to the previous idle-abort/start-RX path if RAIL is not already in RX.
- This tests whether the diagnostic's abort/restart path was dropping the early indirect secured frame. It remains diagnostic-only under `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr/OpenThread remains the default production path.
- Validation passed: both test patches passed `git apply --check`; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both patches afterward; both nested Zephyr/OpenThread checkouts were clean; the debug ELF contains the new `keep existing RX state` marker, the scheduling/stopping poll markers, the +8 dBm marker, pending-RX markers, and widened Child ID Response timeout marker. `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`, `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory`, `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py`, and `git diff --check` passed.
- Next hardware run should confirm the new `keep existing RX state` marker appears after `Sent data poll, fp:yes`; then check whether it is followed by a secured pending frame and `Receive Child Update Response` or `Receive Child ID Response`. Acceptance still requires no fallback, device shell `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP service `deleted:false`.

Fifteenth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence confirmed the keep-existing-RX diagnostic image was flashed: the boot log showed `Thread radio TX power override active: 8 dBm`, receiver-on SRP bootstrap succeeded, `SRP update accepted` was logged, and the post-SRP transition logged `Mode 0x0d -> 0x05` followed by `txing SED test: scheduling attach-mode polls for sleepy Child Update response`.
- The diagnostic confirmed that after a frame-pending data-poll ACK the driver often already reports RAIL RX state and logs `IEEE802154 test: data-poll fp=1 keep existing RX state rail=0x2`. This ruled out the diagnostic's previous RX abort/restart as the sole cause of the missing indirect frame.
- The SED transition still failed. Data-poll ACKs reported `fp:yes`, but no secured pending frame and no `Receive Child Update Response` or rx-off `Receive Child ID Response` arrived before the child detached. During rx-off attach, Parent Responses and unsecure MLE frames were received, but the secured Child ID Response arrived only after fallback restored receiver-on bootstrap mode.
- The OTBR SRP service remaining `deleted:false` is operational recovery evidence from receiver-on fallback, not accepted SED evidence. AC #1 and AC #2 remain open until the device stays attached with `ot mode=n`, `ot pollperiod=5000`, OTBR child-table `R=0`, and SRP `deleted:false`.

Sixteenth test-only SED diagnostic update (2026-06-28):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` to subscribe to and log pending RAIL RX `PACKET_ABORTED`, `FRAME_ERROR`, `ADDRESS_FILTERED`, and `FIFO_OVERFLOW` events while the driver is waiting for indirect data after a data-poll ACK.
- The new marker is `IEEE802154 test: pending-rx event flags=... abort=... frame-error=... filtered=... overflow=...`. This distinguishes "the parent never sent the indirect secured response" from "RAIL saw it but dropped it below normal `RX_PACKET_RECEIVED` delivery."
- This remains diagnostic-only under `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr/OpenThread remains the default production path. Next hardware evidence should look for the new `pending-rx event` marker between `Sent data poll, fp:yes` and `Data poll timeout`.
- Validation passed: both test patches passed `git apply --check`; `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed; `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed; `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both temporary patches afterward; both nested Zephyr/OpenThread checkouts were clean; `git diff --check` passed.
- The rebuilt debug ELF contains `IEEE802154 test: pending-rx event flags=...`, `IEEE802154 test: data-poll fp=1 keep existing RX state rail=...`, `txing SED test: scheduling attach-mode polls for sleepy Child Update response`, `Thread radio TX power override active: %d dBm`, and `txing SED test: Child ID Response timeout:%lu ms`.

Sixteenth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence confirmed the abort/filter/error event diagnostic image was flashed: `Thread radio TX power override active: 8 dBm` appeared, receiver-on SRP bootstrap succeeded, `SRP update accepted` was logged, and the post-SRP transition changed `Mode 0x0d -> 0x05`.
- During the initial SED transition, data-poll ACKs reported `fp:yes` and the driver logged `IEEE802154 test: data-poll fp=1 keep existing RX state rail=0x2`, but no secured pending frame and no `Receive Child Update Response` arrived before the child detached.
- During rx-off attach attempts, Parent Responses and unsecure pending-window frames were received and delivered, but secured Child ID Responses still did not arrive before each `Data poll timeout` / `Child ID Response timeout`. The new `pending-rx event` markers for `FRAME_ERROR` or `ADDRESS_FILTERED` appeared only later, after fallback was already restoring receiver-on bootstrap mode.
- After fallback restored `Mode 0x05 -> 0x0d`, the next attach immediately received secured pending frames and `Receive Child ID Response`, then reattached as child in receiver-on mode. This is operational recovery evidence, not TASK-21.5 acceptance; AC #1 and AC #2 remain open.

Seventeenth test-only SED diagnostic update (2026-06-28):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` to include RAIL `RX_SYNC_0_DETECT`, `RX_SYNC_1_DETECT`, and `RX_FILTER_PASSED` events in the pending indirect-data diagnostic.
- The `IEEE802154 test: pending-rx event ...` marker now includes `sync0=... sync1=... filter-pass=...` in addition to abort, frame-error, address-filtered, and FIFO-overflow flags. The next run should inspect the window between `Sent data poll, fp:yes` and `Data poll timeout`: no sync/filter-pass event means the driver is not seeing a candidate indirect frame start; sync/filter-pass without `RX_PACKET_RECEIVED` points to loss below normal packet delivery.
- This remains diagnostic-only under `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr/OpenThread remains the default production path.
- Validation passed: both test patches passed `git apply --check`; `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed; `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed; `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both temporary patches afterward; both nested Zephyr/OpenThread checkouts were clean; `git diff --check` passed.
- The rebuilt debug ELF contains `IEEE802154 test: pending-rx event flags=... sync0=... sync1=... filter-pass=...`, `IEEE802154 test: data-poll fp=1 keep existing RX state rail=...`, `txing SED test: scheduling attach-mode polls for sleepy Child Update response`, `Thread radio TX power override active: %d dBm`, and `txing SED test: Child ID Response timeout:%lu ms`.

Seventeenth test-only SED diagnostic hardware result (2026-06-28):
- User-run UART evidence confirmed the sync/filter-pass diagnostic image was flashed: `Thread radio TX power override active: 8 dBm` appeared, receiver-on SRP bootstrap succeeded, SRP reached `Registered`, and the post-SRP SED transition changed `Mode 0x0d -> 0x05`.
- The new event markers show the radio does see starts and filter passes during pending windows. After frame-pending data-poll ACKs the logs include `sync0=1` and `filter-pass=1`, but the received packets in the failing SED windows are ACKs, Parent Responses, or unsecure 69-byte MLE advertisement-like frames, not the missing secured Child Update or Child ID Response.
- During rx-off Child ID attempts, data polls still receive ACKs with `fp=1`, then either no non-ACK data frame or only an unsecure frame before `Data poll timeout` / `Child ID Response timeout`. There are no abort, frame-error, address-filtered, or FIFO-overflow indications for a missing secured frame in the failing SED windows.
- After fallback restores receiver-on bootstrap mode (`Mode 0x05 -> 0x0d`), the next Child ID Request immediately receives the secured 126-byte Child ID Response and reattaches as child in receiver-on mode. This confirms the secured response path works when the parent can send directly, but still does not prove accepted SED behavior.
- The current evidence narrows the blocker away from generic RF/link margin and away from a local RAIL packet-drop error. The next manual diagnostic should test whether full network data (`mode=n`) and the near-maximum secured Child ID Response size are part of the failure: after fallback, manually stop Thread, set an rx-off MTD mode without `n`, restart Thread, then compare whether OTBR can show `R=0` and SRP remains registered. This is diagnostic only and not TASK-21.5 acceptance because AC #2 still requires `ot mode=n`.

Manual stable-network-data-only SED diagnostic result (2026-06-28):
- User-run manual shell evidence after fallback set the device to `ot mode -` and restarted Thread. The device did not settle as a child: shell output reported `ot state=detached`, `ot mode=-`, `ot pollperiod=5000`, and `ot parent` returned `InvalidState`.
- OTBR concurrently showed a sleepy minimal child entry for the same extended MAC with `R=0,D=0,N=0`, `QMsgCnt=1`, and supervision interval `129`. This means the parent created/retained a minimal sleepy-child entry and has one queued indirect message, while the device itself did not receive enough of the attach exchange to remain attached.
- UART evidence from the manual mode showed the same pattern as full-network-data SED: Parent Responses are received, Child ID Request is sent, data-poll ACKs report `fp=yes`, and the device then times out in `ChildIdReq`. The child also receives unsecure 69-byte frames during the poll window, but no secured Child ID Response.
- This rules out full network data / the near-maximum `mode=n` Child ID Response as the primary blocker. The remaining evidence points at parent-side indirect transmission or child-side reception of the queued secured indirect response specifically, not generic sleepy attachment metadata.

Manual stable-network-data-only OTBR detail (2026-06-28):
- OTBR `child 40` showed the parent has a concrete child entry for the device: `Mode: -`, `Rloc: 2c28`, `Ext Addr: 5a68b0786a487e55`, `RSSI: -80`, `Link Quality In: 2`, `Timeout: 240`, and `Supervision Interval: 129`.
- OTBR `childip` showed the parent maps the child to both the mesh-local EID and the DUA-like address used by SRP: `fd3f:3117:3b43:7213:127a:98b3:1fe7:9422` and `fde5:a878:868:1:a104:2197:e3ac:645e`.
- The OTBR child table still showed `QMsgCnt=1`, while the device shell remained detached. This reinforces that the parent has queued indirect data for the sleepy child, but the device is not receiving/processing the queued secured response.
- The captured OTBR MAC/MLE counters were cumulative over a long leader runtime (`Time Leader Milli: 760265156`) and therefore not sufficient to isolate the current attempt. They did show high historical `RxErrSec`, but the decisive next evidence needs counters reset immediately before one manual `mode -` attach attempt.

Manual stable-network-data-only isolated OTBR counters (2026-06-28):
- After resetting OTBR MAC/MLE counters immediately before one manual `mode -` attach attempt, OTBR still showed a sleepy minimal child entry with `R=0,D=0,N=0`, `QMsgCnt=1`, child age `6`, RSSI `-87`, and LQI `2`.
- In the isolated MAC counters, OTBR reported `TxAckRequested: 5`, `TxAcked: 5`, `TxDirectMaxRetryExpiry: 0`, `TxIndirectMaxRetryExpiry: 0`, and `RxDataPoll: 0`, while `RxErrSec: 6` incremented during the same short window.
- This is the strongest evidence so far: the parent is acknowledging frames and retains queued indirect data, but it is not processing any valid MAC Data Polls from the sleepy child. The queued message never reaches the indirect transmit path (`TxIndirectMaxRetryExpiry: 0`) because the incoming poll/control exchange appears to fail security validation first (`RxErrSec: 6`).
- The next diagnostic should focus on MAC frame-security state for SED Data Request/Child ID traffic after switching from receiver-on bootstrap to sleepy mode, not on SRP, full network data, RF margin, receive timing, or generic packet filtering.

Eighteenth test-only SED diagnostic update (2026-06-28):
- Updated `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` with opt-in TX-side MAC security logging for the sleepy failure window. The new `IEEE802154 test: tx-sec ...` markers log outgoing frame type, sequence, ACK/security bits, address modes, MHR length, MAC command ID, auxiliary security level/key mode/key index/frame counter, current/previous/next key IDs, destination/source PAN and short/extended addresses, and a first-40-byte TX hexdump.
- This is intended to pair with isolated OTBR counters where `RxErrSec` increments and `RxDataPoll` remains zero. The next hardware run should compare `tx-sec` entries for MAC command Data Request (`type=3`, `cmd=0x04`) and Child ID/MLE data frames against the OTBR child extended MAC and parent-side `RxErrSec` behavior.
- This remains diagnostic-only under `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr/OpenThread remains the default production path.
- Validation passed: both test patches passed `git apply --check`; `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed; `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed; `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both temporary patches afterward; both nested Zephyr/OpenThread checkouts were clean; `git diff --check` passed.
- The rebuilt debug ELF contains the new `IEEE802154 test: tx-sec ...` markers, pending-RX event markers, data-poll frame-pending RX markers, `Thread radio TX power override active: %d dBm`, and the widened Child ID Response timeout marker.

Eighteenth diagnostic hardware result and noise reduction (2026-06-28):
- User-run UART evidence showed the broad TX-side marker was too noisy to be useful. The log was dominated by repeated unsecure and secured MLE/SRP data-frame retries (`type=1`) and ACK timeout logs, plus hexdumps, before the device ever reached `SRP update accepted` or the post-SRP SED transition. The run only showed repeated `SRP update failed: ResponseTimeout (28)`, so it is not useful SED acceptance evidence.
- Narrowed `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch` again so TX diagnostics now emit only a single compact `IEEE802154 test: tx-data-req ...` line for MAC Data Request frames (`type=3`, `cmd=0x04`). The old `tx-sec` address and hexdump markers are removed, and ACK TX markers are gated to MAC command frames so normal data retries no longer flood the UART.
- Pending-RX and frame-pending data-poll markers remain because they are already scoped to the indirect-data window. This keeps the next run focused on the parent-side `RxErrSec`/`RxDataPoll` question without overwhelming the log.
- Validation passed: both test patches passed `git apply --check`; `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed; `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed; `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both temporary patches afterward; both nested Zephyr/OpenThread checkouts were clean; `git diff --check` passed.
- The rebuilt debug ELF contains `IEEE802154 test: tx-data-req ...`, pending-RX event markers, data-poll frame-pending RX markers, `Thread radio TX power override active: %d dBm`, and the widened Child ID Response timeout marker. It no longer contains the old broad `tx-sec` markers.

Nineteenth diagnostic hardware result (2026-06-28):
- User-run UART evidence with the quieter diagnostic image did not exercise SED mode. The device booted, restored/attached as a receiver-on child, selected the SRP server `[fd3f:3117:3b43:7213:dcdb:beb5:731:4235]:53539`, and sent repeated SRP updates, but never logged `SRP update accepted`, `Thread switched to SED mode after SRP registration`, `Mode 0x0d -> 0x05`, or `IEEE802154 test: tx-data-req`.
- The receiver-on bootstrap path is currently failing before SED: every SRP update timed out with `ResponseTimeout (28)` while the host/service stayed in `Adding`. This means TASK-21.5 SED evidence cannot be evaluated from this run.
- The log shows normal receiver-on MLE traffic works well enough to attach and receive Data Responses, but SRP UDP traffic to the server times out. The relevant next check is not another SED firmware change; first re-establish the rx-on SRP baseline by checking OTBR SRP server state, whether the OTBR sees UDP/53539 from the device, and whether the device can ping the selected SRP server mesh-local address.

Receiver-on baseline uplink blocker (2026-06-28):
- User-run baseline checks confirmed the selected SRP server address is a real OTBR address: `sudo ot-ctl ipaddr` included `fd3f:3117:3b43:7213:dcdb:beb5:731:4235`, matching the device-selected SRP server.
- The device was attached as a receiver-on child (`ot state=child`, `ot mode=rn`) and sent a secured ICMPv6 echo request to that OTBR mesh-local address via parent RLOC `0x2c00`, but received no reply.
- A simultaneous OTBR capture on `wpan0` saw no ICMPv6 or UDP/53539 packets. After resetting OTBR MAC counters for the attempt, the parent recorded only one received error frame: `RxErrNoUnknownNeighbor: 1`, with `RxErrSec: 0`, `RxData: 0`, and no IP packet reaching Linux.
- This means current SED diagnostics are blocked by a receiver-on baseline failure below IPv6 delivery. The next diagnostic should clear or refresh Thread parent/child neighbor state, then first prove receiver-on ping and SRP work again before interpreting any SED result.

Receiver-on baseline restored after OTBR restart (2026-06-29):
- User rebuilt and flashed debug firmware, then restarted `otbr-agent`. The receiver-on child baseline recovered: device shell reported `ot state=child`, `ot mode=rn`, parent RLOC `0x2c00`, and link quality in/out `3/3`.
- Device ping to the selected SRP server mesh-local address `fd3f:3117:3b43:7213:dcdb:beb5:731:4235` succeeded with `0.0%` packet loss and an `81 ms` round trip. OTBR `tcpdump` captured both the ICMPv6 echo request and reply on `wpan0`.
- SRP also recovered in receiver-on mode: the client sent an update to the OTBR SRP server on port `53541`, received the response, and logged `SRP update accepted`; host and service states returned to `Registered` for `power-si._txing-coap._udp` on port `5683`.
- OTBR counters after the clean run were healthy: `TxAckRequested: 9`, `TxAcked: 9`, `RxErrNoUnknownNeighbor: 0`, `RxErrSec: 0`, and the child table showed the device as receiver-on (`R=1,D=0,N=1`) with LQI `3`. This confirms the previous receiver-on failure was stale/invalid parent-child neighbor state, not a current firmware IP/SRP path failure.
- With the rx-on baseline restored, TASK-21.5 can return to post-SRP SED transition diagnostics. Acceptance is still open until the device remains attached as `ot mode=n`, OTBR child-table `R=0`, and SRP remains `deleted:false`.

Twentieth SED transition hardware result (2026-06-29):
- User-run UART evidence after the restored receiver-on baseline showed SRP registered successfully in bootstrap mode, then the diagnostic OpenThread patch suppressed the normal rx-on to sleepy reattach: `Mode 0x0d -> 0x05`, `suppressing rx-on to sleepy reattach`, and `scheduling attach-mode polls for sleepy Child Update response`.
- The device sent secured MAC Data Request frames and the parent ACKed with frame-pending, but no secured Child Update Response arrived. The device saw only ACKs or unsecure Parent Response / broadcast-like frames during the pending windows, then detached around 9 seconds after the SED mode change.
- During rx-off attach retries, Parent Responses were received, but Child ID Responses again did not arrive through the sleepy indirect path before the widened 5000 ms MLE timeout. After the app fallback restored receiver-on mode (`Mode 0x05 -> 0x0d`), the next Child ID Request received the secured Child ID Response immediately and reattached.
- Final device and OTBR state were receiver-on recovery, not SED acceptance: device shell reported `ot state=child`, `ot mode=rn`, `ot pollperiod=5000`; OTBR child table showed `R=1,D=0,N=1`, `Mode: r`, and SRP remained `deleted:false`.
- The most useful new counter evidence is the parent/child asymmetry around data polls: the device recorded `TxDataPoll: 11` and `RxErrSec: 0`, while OTBR recorded `RxDataPoll: 0` and `RxErrSec: 7`. In OpenThread, `RxDataPoll` is incremented only after receive security succeeds, so the parent is receiving the MAC Data Request frames but rejecting them before data-poll handling. This keeps the blocker on the secured sleepy MAC Data Request path, not SRP, RF margin, or generic receiver-on IP connectivity.

Software-TX-security SED diagnostic update (2026-06-29):
- Updated the opt-in Zephyr test patch so patched builds use OpenThread software MAC TX security instead of the Zephyr/Silabs `IEEE802154_HW_TX_SEC` path: the patch changes the Silabs S2 default for `OPENTHREAD_MAC_SOFTWARE_TX_SECURITY_ENABLE` to `y` and removes `IEEE802154_HW_TX_SEC` from the Silabs radio capabilities while the patch is applied.
- The same patch now also emits a bounded post-security byte dump for MAC Data Request frames with marker `IEEE802154 test: tx-data-req secured bytes[0..47]`. This keeps logging focused on the frames OTBR rejects with `RxErrSec`.
- This remains diagnostic-only under `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1`; stock Zephyr/OpenThread remains the default production path and the local Zephyr/OpenThread checkouts are reversed after the build.
- Validation passed: both test patches passed `git apply --check`; `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed; `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 10 tests; `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed: 3 tests; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex` and reversed both temporary patches afterward.
- Artifact checks passed: patched debug `.config` contains `CONFIG_OPENTHREAD_MAC_SOFTWARE_TX_SECURITY_ENABLE=y`; the debug ELF contains `IEEE802154 test: tx-data-req secured bytes[0..47]`, `tx-data-req seq`, pending-RX event markers, the SED transition scheduling marker, and `Thread radio TX power override`; both nested Zephyr/OpenThread checkouts were clean after patch reversal; `git diff --check` passed.
- Next hardware evidence should compare OTBR counters after the SED transition. If `RxDataPoll` increments and `RxErrSec` stops increasing, the Zephyr/Silabs TX-security path is the likely root cause. If `RxErrSec` still increments with OpenThread software TX security, the bug is higher in the child/parent MAC frame-counter or key-state synchronization.

Software-TX-security SED hardware result (2026-06-29):
- User-run hardware evidence with the opt-in software-TX-security debug image is the first successful SED transition. The device registered SRP in receiver-on bootstrap mode, switched `Mode 0x0d -> 0x05`, logged `Thread switched to SED mode after SRP registration`, received `Receive Child Update Response as child`, then stopped the temporary transition polls.
- After the transition, the UART log showed steady 5 second MAC Data Request polls with `Sent data poll, fp:no` and no `Data poll timeout`, fallback, or `Role child -> detached` markers in the captured post-transition window.
- OTBR evidence after restart showed a sleepy child entry for extended MAC `5a68b0786a487e55` with `R=0,D=0,N=1`, `QMsgCnt=0`, LQI `3`, and counters `RxDataPoll: 13`, `RxErrSec: 0`, `TxAcked: 12/12`. This is the counter pattern missing from the stock Zephyr/Silabs hardware-TX-security runs.
- This strongly confirms the TASK-21.5 SED blocker is the Zephyr/Silabs `IEEE802154_HW_TX_SEC` path for secured MAC Data Request frames. When OpenThread secures those frames in software, the parent accepts them as data polls and the indirect Child Update Response is delivered.
- AC #2 is still not checked because the formal hardware evidence still needs final device-shell output after the SED transition (`ot state`, `ot mode`, `ot pollperiod`) and a post-transition OTBR `srp server service` check showing `power-si._txing-coap._udp.default.service.arpa` remains `deleted:false` on port `5683`.
- AC #1 remains open because this evidence was produced by an opt-in diagnostic Zephyr patch. Production still needs either a stock-Zephyr upstream fix/configuration path for Silabs SED MAC TX security or an explicit decision to carry a downstream Zephyr workaround.

Extended software-TX-security SED hardware result (2026-06-29):
- Follow-up user-run evidence showed the software-TX-security image did not remain in accepted SED steady state indefinitely. The device later logged `Thread SED mode did not remain attached: role=detached rxOnWhenIdle=0; reverting to SRP bootstrap mode`, then switched `Mode 0x05 -> 0x0d`, restarted Thread in SRP bootstrap mode, and reattached as a receiver-on child.
- Final device shell output reported `ot state=child`, `ot mode=rn`, `ot pollperiod=5000`, and a healthy parent link. OTBR likewise showed SRP still `deleted:false`, but the child table showed `R=1,D=0,N=1` and `child 1` reported `Mode: r`.
- The parent counters are still useful: `RxDataPoll: 64` and `RxErrSec: 0` confirm the software-TX-security workaround lets OTBR accept data polls. The remaining failure is now long-run SED stability or reattach behavior, not the original MAC Data Request security rejection.
- To isolate that, the opt-in test patch stack was narrowed again. `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1` now applies only the minimal Zephyr/Silabs workaround: set `OPENTHREAD_MAC_SOFTWARE_TX_SECURITY_ENABLE=y` for Silabs S2 and stop advertising `IEEE802154_HW_TX_SEC`. The temporary OpenThread core transition patch and all `txing SED test` / `IEEE802154 test` diagnostic logging were removed from the build path.
- Validation passed after narrowing the patch: the remaining Zephyr patch passed `git apply --check`; `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py` passed; `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` passed: 10 tests; `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` passed: 3 tests; `TXING_POWER_SI_ZEPHYR_SED_TEST_PATCH=1 just power-si::mcu::build-debug` rebuilt `devices/power-si/mcu/build/zephyr-xiao_mg24-debug/zephyr/zephyr.hex`.
- Artifact checks passed: patched debug `.config` contains `CONFIG_OPENTHREAD_MAC_SOFTWARE_TX_SECURITY_ENABLE=y`, `CONFIG_OPENTHREAD_MTD_SED=y`, and `CONFIG_OPENTHREAD_POLL_PERIOD=5000`; the debug ELF contains the app's `Thread switched to SED mode after SRP registration` marker but no `txing SED test` or `IEEE802154 test` diagnostic markers; both nested Zephyr/OpenThread checkouts were clean after patch reversal.

Minimal software-TX-security SED acceptance evidence (2026-06-29):
- User-run hardware evidence with the narrowed minimal workaround image satisfied AC #2. The UART log shows SRP registration, then `Mode 0x0d -> 0x05`, `Thread switched to SED mode after SRP registration`, a brief reattach as sleepy mode `0x05`, and no fallback marker in the captured steady-state window.
- The device shell at the end of the run reported `ot state=child`, `ot mode=n`, `ot pollperiod=5000`, and parent link quality in/out `3/3`.
- OTBR evidence showed `power-si._txing-coap._udp.default.service.arpa` remained `deleted:false` on port `5683`, and the later child table showed extended MAC `5a68b0786a487e55` as `R=0,D=0,N=1`, `QMsgCnt=0`, LQI `3`, RSSI `-78`, supervision interval `129`.
- OTBR counters remained healthy under SED: `RxDataPoll: 185`, `RxErrSec: 0`, `RxErrNoUnknownNeighbor: 0`. The first server sample with an empty child table appears to have caught the device between detach/reattach or before the accepted sleepy child entry was present; the later sample and device shell are the acceptance evidence.
- AC #1 remains open because the working image still depends on the minimal opt-in Silabs TX-security workaround. Production needs a stock Zephyr/upstreamable mechanism for disabling the broken `IEEE802154_HW_TX_SEC` path or an explicit decision to carry the downstream workaround.

SED test/current profile cleanup (2026-07-01):
- The upstream Zephyr/Silabs issue has been filed externally, so the repo now treats the local software-TX-security change as a named test profile instead of an ambient env-var-only diagnostic. `just power-si::mcu::build-sed-debug` builds a serial/shell SED functional test image in `devices/power-si/mcu/build/zephyr-xiao_mg24-sed-debug`, and `just power-si::mcu::build-sed-current` builds a silent PM-enabled current-measurement image in `devices/power-si/mcu/build/zephyr-xiao_mg24-sed-current`.
- Both SED profiles apply and reverse only `devices/common/mcu/patches/silabs-efr32-sed-data-poll-rx-test.patch`, which enables OpenThread software MAC TX security for Silabs S2 and removes the Silabs `IEEE802154_HW_TX_SEC` capability while the build runs. Normal `build` and `build-debug` remain stock-source profiles.
- The previous debug TX-power override was removed from the standard debug path. Functional SED evidence should use `sed-debug`; current measurement should use `sed-current`, which enables `CONFIG_PM=y` and disables UART/log output so the board can sleep between 5000 ms polls.
- AC #1 remains open because stock Zephyr/Silabs hardware TX security still does not provide the accepted SED behavior without the local workaround.

Hardware-TX-security retry candidate and CCM isolation (2026-07-17):
- The earlier software-TX-security workaround was removed from the named SED profiles. `sed-debug` and `sed-current` now apply only `devices/common/mcu/patches/silabs-efr32-stack-triggered-retries-test.patch`, a test-only extension of the upstream Silabs stack-retry candidate. It leaves `IEEE802154_HW_TX_SEC` enabled and normal `build`/`build-debug` profiles remain stock.
- User-run hardware evidence with the upstream candidate preserved receiver-on SRP bootstrap and registration, then switched to SED and failed in the same indirect-response path. The first five failed Data Requests were all fresh transmissions (`reused=0`), so retry preservation is not exercised by the observed first-poll failure.
- The test patch now records those five final secured Data Requests and independently reconstructs their zero-payload CCM* MIC with the existing radio AES-ECB primitive. It logs only match status and truncated MICs (`SED test: data-poll CCM ECB-match=...`), never key material, and does not modify a transmitted frame. This distinguishes a zero-payload hardware CCM mismatch from a receive/indirect-delivery failure before any behavior-changing workaround is considered.
- Validation: `just power-si::mcu::build-sed-debug` passed and produced `devices/power-si/mcu/build/zephyr-xiao_mg24-sed-debug/zephyr/zephyr.hex`; the temporary patch was reversed and the Zephyr checkout was clean afterward. Generated config retains hardware TX security (`CONFIG_OPENTHREAD_MAC_SOFTWARE_TX_SECURITY_ENABLE` unset), MTD SED, `5000 ms` polling, and `CONFIG_OPENTHREAD_MIN_RECEIVE_ON_AFTER=5504`. Focused Python tests and `git diff --check` passed.
- Next hardware evidence: manually flash `sed-debug`, then preserve the first five `CCM ECB-match` lines with device `ot state`/`ot mode`/`ot pollperiod` and OTBR child, SRP, and MAC-counter output. AC #1 and AC #2 remain open pending a stable stock-hardware-security SED result.

Zero-payload CCM behavioral-oracle test patch (2026-07-18):
- Subsequent user-run evidence confirmed the test candidate's independent CCM* calculation disagrees with every first five fresh hardware-secured Data Request (`CCM ECB-match=0`, `reused=0`). OTBR simultaneously reported `RxErrSec` increasing and `RxDataPoll=0`, which proves it received and rejected the polls before indirect-data handling. The retry candidate cannot fix that fresh-frame defect.
- `devices/common/mcu/patches/silabs-efr32-zero-payload-data-request-mic-test.patch` is a separate, dependent test patch. It leaves `IEEE802154_HW_TX_SEC` enabled and lets the Silabs hardware CCM path run first, then replaces only a mismatching four-byte MIC for a zero-payload, security-level-5 MAC Data Request with the independently reconstructed CCM* value. It does not change encryption, keys, frame counters, non-Data-Request frames, or nonzero payloads. It is a behavioral oracle for the upstream issue, not a production workaround or an upstream-ready patch.
- The build helper now applies test patches one at a time, in order, and reverses only patches that were successfully applied. This permits the second patch to depend on the first and prevents a failed second application from leaving the first in the stock Zephyr checkout. Normal release/debug profiles still apply no patches.
- Validation passed: `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py` (3 passed); `python3 -m unittest devices.common.mcu.tests.test_power_si_sed_config devices.common.mcu.xiao_mg24.tests.test_thread_factory` (11 passed); `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`; `just power-si::mcu::build-sed-debug`; `just power-si::mcu::build-sed-current`; and `git diff --check`. Both builds applied/reversed both patches and left the Zephyr checkout clean. The debug ELF includes `SED test: corrected zero-payload data-request MIC`; its config retains `CONFIG_OPENTHREAD_MTD_SED=y`, `CONFIG_OPENTHREAD_POLL_PERIOD=5000`, and software TX security unset.
- The test-only trace counters now saturate after their first five records rather than using post-increment guards, so extended 5000 ms SED runs do not resume diagnostics after an 8-bit counter wraps.
- Next hardware evidence: manually flash only the already-built `sed-debug` HEX, remove the old SRP service first, then capture the correction markers, final `ot state`/`ot mode`/`ot pollperiod`, and OTBR child/service/MAC counters. A successful oracle run must show `RxDataPoll` increasing, `RxErrSec: 0`, child `R=0`, SRP `deleted:false`, and durable `ot mode=n`; it does not close the stock-Zephyr acceptance criteria.

First zero-payload CCM behavioral-oracle hardware result (2026-07-18):
- The user-run `sed-debug` log shows receiver-on bootstrap attachment and SRP registration succeeding, followed by the intended SED transition: `Mode 0x0d -> 0x05`, `rxOnWhenIdle=0`, and `poll=5000 ms`.
- Every captured fresh security-level-5 zero-payload MAC Data Request still showed a raw hardware/ECB MIC mismatch. The test patch logged the original hardware MIC, replaced it with the independently reconstructed MIC, and the subsequent `data-poll tx` line contained that reconstructed value. This is direct on-air-frame evidence for the suspected hardware CCM defect while retaining `IEEE802154_HW_TX_SEC`.
- The first two corrected polls received frame-pending ACKs and then the secured Child ID Response. The device completed the SED reattach and later reported `ot state=child`, `ot mode=n`, and `ot pollperiod=5000`; following 5-second polls reported `fp:no`, consistent with an attached child with no queued indirect traffic.
- Acceptance remains open pending OTBR-side proof from this same run: child-table `R=0`, SRP `deleted:false`, `RxDataPoll` increasing, `RxErrSec: 0`, and a queued indirect-delivery ping. This is still a test-only behavioral oracle, not stock-Zephyr or production acceptance.

Zero-payload CCM behavioral-oracle OTBR acceptance evidence (2026-07-18):
- With the device already reporting `ot state=child`, `ot mode=n`, and `ot pollperiod=5000`, OTBR showed child ID `4` / RLOC `0x2c04` with `R=0,D=0,N=1`, link quality `3`, and no queued messages. The SRP service remained `deleted:false` on port `5683` with `type=power-si` and `pv=1`.
- After an OTBR MAC-counter reset, three queued ICMPv6 echo requests to the SRP address all received replies with no packet loss. The 207 ms, 4218 ms, and 3298 ms round trips are within the expected one-poll-window behavior for a 5000 ms SED period.
- The isolated OTBR counters recorded `RxDataPoll: 3`, `RxErrSec: 0`, `TxAcked: 3/3`, and no MAC receive/transmit errors. The child remained `R=0` and the SRP service remained active after the ping test.
- This completes AC #2 for the debug behavioral-oracle profile. AC #1 remains open: the successful image still temporarily corrects a proven hardware-generated MIC mismatch and therefore is not stock-Zephyr production acceptance.

Focused RadioAES CCM upstream candidate (2026-07-18):
- The retry-preservation candidate and the runtime MIC-correction oracle are no longer in the active `sed-debug`/`sed-current` build path. The observed failed Data Requests were fresh transmissions, and the oracle was valuable evidence but not an upstreamable fix.
- The first isolated RadioAES candidate only replaced the contents of the all-invalid dummy input buffer. User-run `sed-debug` evidence reproduced the same `fp:yes`/`DataPollSender: Data poll timeout` failure after the SED switch. The stock HAL still described the input as a 16-byte `AESPAYLOAD` descriptor with `invalidBytes=16`, so that candidate did not remove the defective empty-message representation.
- The active isolated patch remains `devices/common/mcu/patches/silabs-radioaes-zero-length-ccm.patch`. It applies only to the owning `hal_silabs` checkout during named SED builds and is reversed afterward. For `encrypt && length == 0 && tag_length > 0`, it bypasses the RadioAES CCM dummy-payload descriptor and derives the CCM tag with the existing RadioAES ECB primitive: CBC-MAC over B0 plus formatted AAD, XORed with S0. This is the same construction independently proven by the earlier behavioral oracle, but it is now performed in the owning HAL rather than by post-processing an emitted IEEE 802.15.4 frame.
- The candidate keeps `IEEE802154_HW_TX_SEC` enabled and makes no IEEE 802.15.4 driver, retry, frame-counter, MIC-rewrite, logging, Matter, or OTBR change. Normal release/debug builds remain stock-source builds.
- The candidate is deliberately narrowed to empty encrypted CCM messages with a nonzero tag. Zero-length decrypt-and-verify, CCM-star messages without a tag, and all nonempty payloads continue through the upstream implementation. The CBC-MAC/S0 construction was checked independently against Node's AES-CCM implementation for a zero-payload vector. Focused hardware validation is recorded below; upstream disposition remains pending.
- The profile flash helper now passes its verified profile-specific HEX to the Zephyr pyOCD runner explicitly instead of relying on the runner to infer one from the build directory. A `just power-si::mcu::flash sed-debug` invocation must print `--hex-file .../zephyr-xiao_mg24-sed-debug/zephyr/zephyr.hex`; this makes a silent `sed-current` or stale-profile flash distinguishable from a firmware/runtime failure. Focused flash-helper tests passed.
- The changed source is owned by `zephyrproject-rtos/hal_silabs`, but its issue tracker is disabled. Report and discuss this candidate on the existing Zephyr issue `zephyrproject-rtos/zephyr#112473`, naming `simplicity_sdk/platform/security/sl_component/sl_protocol_crypto/src/sli_protocol_crypto_radioaes.c` as the affected path. The completed hardware run established fresh `RxDataPoll` growth, `RxErrSec: 0`, successful indirect delivery, durable `ot mode=n`, child-table `R=0`, and active SRP without behavioral MIC correction.
- AC #1 remains open because the working profile still carries the isolated downstream candidate; upstream acceptance or an equivalent stock Zephyr fix is required for production acceptance.

RadioAES candidate diagnostic profile (2026-07-18):
- The first hardware run of the focused HAL candidate reproduced the original failure. Receiver-on bootstrap and SRP registration completed, then `Mode 0x0d -> 0x05` caused a SED reattach in which every `Sent data poll, fp:yes` timed out. It is therefore not evidence that the candidate emits a valid zero-payload CCM MIC.
- `sed-diagnostic` is a separate serial/shell profile. It applies the same isolated HAL candidate plus `devices/common/mcu/patches/silabs-efr32-empty-ccm-diagnostic.patch` to the Zephyr driver for that build only. The driver records the first three zero-payload secured MAC-command AAD, nonce, and emitted MIC values after CCM completes, never key material or frame contents beyond the command header.
- `just power-si::mcu::build-sed-diagnostic` completed and produced `devices/power-si/mcu/build/zephyr-xiao_mg24-sed-diagnostic/zephyr/zephyr.hex`. The build helper reversed both patches afterward; focused stock-MCU pytest and Python compilation checks passed. The following hardware result captured its three `empty TX CCM` records and matching OTBR evidence.

RadioAES candidate diagnostic hardware result (2026-07-18):
- The `sed-diagnostic` image completed receiver-on bootstrap and SRP registration, then switched `Mode 0x0d -> 0x05`. During its SED reattach it logged two 34-byte, 28-byte-AAD, zero-payload secured MAC Data Requests with emitted MICs, each followed by `Sent data poll, fp:yes`.
- The parent then delivered the secured Child ID Response. The device returned to `role=child` with mode `0x05`; its next logged zero-payload MAC command was a normal 22-byte short-address Data Request followed by `Sent data poll, fp:no`, and the subsequent five-second polls remained `fp:no`. This is the previously missing indirect response and is direct evidence that the candidate-generated MICs are accepted for the reattach path.
- OTBR currently shows the child with `R=0,D=0,N=1` and the SRP service remains `deleted:false` on port `5683`. Its displayed `RxDataPoll: 566` and `RxErrSec: 175` are cumulative from earlier runs: the 31-second diagnostic boot contains only the logged initial polls, so those values cannot be attributed to this candidate image. Do not use that sample for acceptance.
- Fresh OTBR acceptance followed a counter reset: after 20 seconds it recorded `RxDataPoll: 4`, `RxErrSec: 0`, child `R=0,D=0,N=1`, and active SRP. Three queued ICMPv6 echo requests then received three replies with no loss and 354-2170 ms round trips; counters increased to `RxDataPoll: 9` with `RxErrSec: 0`.
- Device evidence showed frame-pending polls retrieving each queued ICMPv6 request, sending Echo Replies, then returning to regular `fp:no` five-second polls. After more than five minutes it reported `ot state=child`, `ot mode=n`, and `ot pollperiod=5000`. This proves the candidate profile meets the hardware behavior expected of the bounded-latency SED. It does not close AC #1 because release/debug builds remain unmodified stock-source profiles.

RadioAES upstream-submission cleanup (2026-07-18):
- Removed the temporary `sed-diagnostic` profile and its Zephyr-driver trace patch. The earlier AAD/nonce/MIC records remain historical evidence only; the active candidate contains no logging or driver instrumentation.
- The only active downstream patch is `devices/common/mcu/patches/silabs-radioaes-zero-length-ccm.patch`. It changes `hal_silabs` only for encrypted CCM messages with zero plaintext and a nonzero tag, deriving the tag from B0, formatted AAD, and S0 with the existing RadioAES ECB primitive. It leaves hardware TX security, retries, frame counters, decryption, CCM-star without a tag, and nonempty payloads on their existing paths.
- Validation passed: `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py -q` (3 passed); `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`; `git apply --check` against the clean `hal_silabs` checkout; `git diff --check`; and `CCACHE_DISABLE=1 just power-si::mcu::build-sed-debug`. The build compiled the candidate, produced the SED debug HEX, reversed the patch, and left both nested Zephyr checkouts clean.

2026-07-18: User approved a sed-debug-only recovery experiment: no receiver-on fallback after SED activation; reconnect only as SED.

SED-only recovery experiment implementation (2026-07-18):
- Added `CONFIG_TXING_POWER_SI_SED_RECOVERY_TEST`, enabled exclusively by the new `sed-debug` profile overlay.
- After post-SRP SED activation, persistent loss now retries Thread in SED link mode only: at most three attempts with 5, 10, and 20 second delays. It never invokes the receiver-on bootstrap restart after SED activation. Release, ordinary debug, and sed-current retain the existing one-shot receiver-on fallback.
- Added static profile/recovery contract tests and documented expected logs and OTBR checks. `devices/common/mcu/.venv/bin/python -m unittest devices.common.mcu.tests.test_power_si_sed_config -v` passed (5 tests); `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py -q` passed (4 tests); `just power-si::mcu::build-sed-debug` and `just power-si::mcu::build-debug` completed successfully before this note. The sed-debug generated configuration contains `CONFIG_OPENTHREAD_MTD_SED=y`, `CONFIG_OPENTHREAD_POLL_PERIOD=5000`, and `CONFIG_TXING_POWER_SI_SED_RECOVERY_TEST=y`; ordinary debug does not contain the test flag.
- Hardware validation is pending. Test must show child mode `n`, 5000 ms polling, OTBR `R=0`, continued SRP registration, and no receiver-on fallback log after a lost SED attachment.

SED-only recovery first hardware capture (2026-07-18):
- The sed-debug image completed receiver-on bootstrap and SRP registration, then switched to SED (`Mode 0x0d -> 0x05`) and immediately detached as expected for this board/path.
- Stock OpenThread reattached the child in SED mode without application intervention at 00:00:23.618 after the transition and again at 00:01:15.550 after a later data-poll no-ACK detach. Both reattachments received a frame-pending Data Poll followed by a secured Child ID Response; saved NetworkInfo remained `mode:0x05`.
- No `Thread SED attachment lost`, `Thread restarted in SED mode during SED recovery`, or receiver-on fallback log appears because each OpenThread recovery completed before the application 20-second guard. This is intended: the bounded application recovery must not race a successful native SED reattach.
- The capture includes an approximately 20-second no-ACK recovery interval, so follow-up hardware evidence should include OTBR child/SRP/MAC-counter status after the second reattach. To exercise the explicit app recovery branch, hold the only parent unavailable until the `Thread SED attachment lost ... scheduling SED recovery` log appears, then restore it; device must remain SED throughout.

SED-only recovery deterministic hardware validation (2026-07-18):
- User ran `ot thread stop` from an attached sed-debug child. The device changed `child -> detached -> disabled` at 00:04:18.9; the app then logged `Thread SED attachment lost: role=disabled rxOnWhenIdle=0; scheduling SED recovery 1/3 in 5 s` at 00:04:38.961.
- At 00:04:43.975 it logged `Thread attempting SED recovery 1/3`; at 00:04:44.023 it logged `Thread restarted in SED mode during SED recovery`. It then received a parent response and frame-pending data poll / secured Child ID Response, returning `detached -> child` at 00:04:47.590. Saved NetworkInfo records `mode:0x05`.
- Final device shell evidence: `ot state=child`, `ot mode=n`, `ot pollperiod=5000`. Final OTBR evidence: child RLOC 0x2c06 with `R=0,D=0,N=1`, and `power-si._txing-coap._udp.default.service.arpa` remains `deleted:false` on port 5683. No receiver-on fallback log occurred.
- This validates the sed-debug bounded SED-only recovery branch. The isolated RadioAES candidate remains a downstream dependency, so AC #1 stays open; production/release fallback policy is unchanged.

sed-current implementation update (2026-07-18):
- `devices/power-si/mcu/zephyr/current.conf` now enables the same bounded SED-only recovery policy as `sed-debug`, while retaining Thread/SRP/CoAP, safe GPIO behavior, `CONFIG_PM=y`, and tickless idle. It disables `LOG`, serial, console, UART console, printk, boot banner, shell, net shell, OpenThread shell, and OpenThread debug output.
- This makes sed-current intentionally silent and prevents a lost SED attachment from switching to receiver-on mode. It is intended for representative steady-state SED current after sed-debug has already proved attach, SRP, and indirect delivery.
- Verified build: `CCACHE_DISABLE=1 just power-si::mcu::build-sed-current` completed successfully, emitted `devices/power-si/mcu/build/zephyr-xiao_mg24-sed-current/zephyr/zephyr.hex`, and applied then reversed `silabs-radioaes-zero-length-ccm.patch`; the `hal_silabs` checkout is clean afterward.
- Generated config confirms `CONFIG_OPENTHREAD_MTD_SED=y`, `CONFIG_OPENTHREAD_POLL_PERIOD=5000`, `CONFIG_OPENTHREAD_SRP_CLIENT=y`, `CONFIG_OPENTHREAD_COAP=y`, `CONFIG_TXING_POWER_SI_SED_RECOVERY_TEST=y`, `CONFIG_PM=y`, `CONFIG_TICKLESS_KERNEL=y`, and disabled serial/log/console/printk/banner/shell/OpenThread debug settings.
- Validation passed: `devices/common/mcu/.venv/bin/python -m unittest devices.common.mcu.tests.test_power_si_sed_config -v` (5 tests); `devices/common/mcu/.venv/bin/python -m pytest devices/common/mcu/tests/test_stock_zephyr_mcu.py -q` (4 tests); `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py`; and `git diff --check`.
<!-- SECTION:NOTES:END -->
