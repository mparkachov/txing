---
id: TASK-21.4
title: power-si release docs and hardware acceptance are complete
status: Done
assignee:
  - '@Codex'
created_date: '2026-06-20 07:12'
updated_date: '2026-07-27 19:03'
labels: []
milestone: m-0
dependencies:
  - TASK-21.1
  - TASK-21.2
  - TASK-21.3
  - TASK-21.5
references:
  - rig/docs
  - docs/installation.md
  - docs/components/rig.md
documentation:
  - >-
    backlog/docs/milestones/power-si-thread-device/doc-22 -
    Milestone-power-si-Thread-device-type.md
parent_task_id: TASK-21
priority: medium
ordinal: 48000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make the power-si Thread runtime operationally usable by packaging the new rig daemon, documenting OTBR and provisioning prerequisites, and recording manual hardware acceptance evidence.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Rig build, release, mise/service, and installation documentation include txing-thread-connectivity as the third daemon without changing existing BLE/Sparkplug service semantics.
- [x] #2 Documentation explains external OTBR prerequisites, power-si factory provisioning, manual firmware/factory flashing commands, and the rule that real Thread dataset TLVs are never committed.
- [x] #3 Automated validation results are recorded for MCU, rig Go, shared AWS/Python, and Office tests relevant to power-si.
- [x] #4 Manual acceptance evidence covers user-run factory provisioning, firmware flashing, SRP registration, rig discovery, REDCON 4/3 transitions, D1 output, battery shadow updates, and Sparkplug birth/data/death behavior.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Preserve the existing release/hardware-acceptance scope. 2. Correct the standalone rig node MQTT client ID to its rig Thing name, keeping node topics/will and device sessions stable. 3. Add focused tests and update lifecycle/rig documentation. 4. Run rig validation; retain TASK-21.4 manual hardware acceptance as the closing gate.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
- Expanded `devices/power-si/README.md` from the initial contract stub into the operator-facing procedure for rig prerequisites, external OTBR expectations, TXT1 factory data, dataset TLV secrecy, firmware build, manual firmware/factory flashing command shapes, and hardware acceptance evidence capture.
- Updated `docs/installation.md` so the raspi rig setup path explicitly covers BLE and Thread-managed devices, keeps OTBR installation external, and points `power-si` operators to the device provisioning/flashing guide.
- Fixed `docs/artifacts.md` so the rig asset list includes `txing-thread-connectivity-linux-aarch64.tar.gz` alongside the existing Sparkplug and BLE daemon assets.
- Corrected the `power-si` flashing procedure to use Zephyr's stock pyOCD runner over the XIAO MG24 onboard CMSIS-DAP debugger instead of assuming J-Link, and clarified how to turn `ot-ctl dataset active -x` output into the TLV hex file consumed by the factory tool.
- Aligned MCU tooling with the final command surface: root `mcu` exposes no firmware flash recipe; `just power-si::mcu::flash` programs the built firmware through Zephyr's stock pyOCD runner; `just mcu::nve <thing-name> <dataset-tlvs-file>` generates and programs the `power-si` TXT1 factory record while the existing one-argument `just mcu::nve <thing-name>` keeps the nRF TXR1 behavior.
- Switched `power-si` firmware and TXT1 factory programming to Zephyr's stock `west flash -r pyocd` path over the onboard CMSIS-DAP debugger, with `mcu::install` installing Zephyr runner Python requirements, requesting the `EFR32MG24B220F1536IM48` pyOCD CMSIS target pack, and verifying that pyOCD can see `EFR32MG24B220F1536IM48`. The existing nRF OpenOCD flashing path remains unchanged.
- Manual hardware acceptance is still pending. No hardware flashing/programming, OTBR discovery, SRP registration, REDCON transitions, D1 measurement, battery shadow observation, or Sparkplug birth/data/death hardware evidence was run or available in this session.

Manual hardware evidence update (2026-06-26):
- The operator provisioned the power-si TXT1 factory record with `just mcu::nve power-si tmp/power-si-dataset.hex`; the factory generator targeted `0x0817a000` and validated a 111-byte dataset without recording its TLVs.
- The operator removed the prior SRP registration from debug firmware with `ot srp client host remove 1 1` and observed the service as `deleted: true` on OTBR.
- The operator flashed the production image. No UART output was expected because the release configuration disables serial, console, shell, and log backends.
- OTBR then reported a fresh `power-si._txing-coap._udp.default.service.arpa.` service with `deleted: false`, port `5683`, TXT `type=power-si` and `pv=1`, proving release firmware read TXT1 factory data and completed SRP registration.

TASK-21.4 AC #4 remains open. Still required: real rig DNS-SD discovery; rig CoAP GET state and REDCON 4/3 command confirmation; D1/LED measurements; Thread/power shadow evidence; and Sparkplug DBIRTH/DDATA/DDEATH evidence. The MCU currently reports `batteryMv: null`, so battery-shadow acceptance also requires battery measurement implementation before it can be demonstrated. TASK-21.5 has updated the firmware/software contract to a 5 second poll Thread SED, but user-run hardware evidence must still prove the SED child-table mode and SRP registration before final acceptance can close.

SED follow-up split (2026-06-26): created TASK-21.5 to restore the original power-si Sleepy End Device intent with 5 second poll latency and 12 second rig Thread CoAP timeout. TASK-21.4 remains open for release documentation and hardware acceptance evidence, and now depends on TASK-21.5 before final acceptance can close.

TASK-21.5 software update (2026-06-26): power-si firmware and docs now target a 5 second poll Thread SED. TASK-21.4 AC #4 still requires user-run hardware evidence for SED mode, rig discovery, REDCON 4/3, D1/LED, Thread/power shadows, and Sparkplug DBIRTH/DDATA/DDEATH behavior.

User approved a prerequisite raspi node-connectivity correction before TASK-21.4 closes: align the standalone Sparkplug node MQTT client ID with the rig Thing name so AWS IoT connectivity indexing reflects the live manager session. Preserve Sparkplug topics/will and managed-device sessions.

Implemented the approved raspi node-connectivity correction: NodeClientID now returns the rig Thing name, so the standalone node MQTT connection is indexed against the rig Thing. Updated lifecycle/rig docs with the one-runtime-per-rig-client constraint. The NDEATH topic remains spBv1.0/<town>/NDEATH/<rig>; device MQTT client IDs are unchanged. Validation passed: go test -race ./internal/manager ./cmd/txing-sparkplug-manager; go vet ./...; just rig::test.

Manual evidence update (2026-07-27, no dataset TLVs recorded): sed-debug power-si-g5i08j shell reported role=child and ot mode n. OTBR child table showed RLOC16 0x2c06 with receiver-on flag R=0; SRP service was deleted:false on port 5683 with type=power-si, pv=1, and profile=sed-debug. After Thread daemon 0.16.3 restart, inventory reconciled one device. Logged 4->3 command/confirmation 2026-07-27T17:41:53.539143165Z -> 17:42:01.278173332Z (7.739s, requestedLinkMode=rn); 3->4 was 17:42:11.809410193Z -> 17:42:11.947718082Z (138ms, requestedLinkMode=n). Operator confirmed Office and LED state remained in sync. Thread shadow reported online=true, current address/host/port/service/protocolVersion. Operator also confirmed the rig and device connectivity Console behavior after the node client-ID correction.

Additional manual evidence (2026-07-27): operator flashed/ran sed-current. Thread daemon logged REDCON 4->3 command at 2026-07-27T18:45:55.886829029Z and confirmed REDCON 3 at 2026-07-27T18:46:02.188383617Z (6.302s, requestedLinkMode=rn). At REDCON 3, OTBR child table reported the same child with receiver-on flag R=1. The power named shadow reported batteryMv=3968, proving battery measurement and power-shadow forwarding. No Thread dataset TLVs recorded.

Additional manual evidence (2026-07-27): operator measured D1 directly at 3.33 V in REDCON 3. Its state matched the board LED and Office REDCON state; prior REDCON 4 observations established the corresponding off state. This completes the required direct D1/LED evidence.

Additional manual lifecycle evidence (2026-07-27, Console event timeline): operator disconnected power-si-g5i08j and observed presence/disconnected at 20:57:39 CEST, with two sparkplug named-shadow update acceptances at the same timestamp. After reconnection, thread and power shadow updates were accepted at 20:57:51; presence/connected occurred at 20:57:53 with two further sparkplug named-shadow update acceptances; later power updates were accepted at 20:57:53 and 20:58:07. This confirms a real per-device MQTT disconnect in the middle and fresh reconnect/lifecycle projection on recovery. Preserve exact Sparkplug message-type capture before closing AC #4.

Direct Sparkplug MQTT capture (2026-07-27): `spBv1.0/town-jhgjjd/DDEATH/raspi-6q6abe/power-si-g5i08j` observed at 21:00:29 CEST after the controlled disconnect. Recovery produced `spBv1.0/town-jhgjjd/DBIRTH/raspi-6q6abe/power-si-g5i08j` at 21:00:51 CEST; decoded payload carried redcon=3 and capability.power=true, capability.sparkplug=true, capability.thread=true. This is direct DDEATH/DBIRTH evidence, not inferred from shadow projections. Remaining Sparkplug evidence: one DDATA after a REDCON transition.

Final direct Sparkplug DDATA evidence (2026-07-27): DCMD.redcon=3 was captured at 21:02:19 CEST for dcmd-power-si-g5i08j-17. The manager published accepted DDATA at 21:02:19 with redcon=4, status=accepted, target=3; it then published confirmed DDATA at 21:02:20 with redcon=3, capability.power/sparkplug/thread=true, followed by succeeded DDATA with the same command correlation and target. Together with the 21:00:29 DDEATH and 21:00:51 recovered DBIRTH capture, this completes direct DBIRTH/DDATA/DDEATH lifecycle evidence.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed TASK-21.4 manual hardware acceptance. Operator evidence covers TXT1 provisioning and production flash, fresh SRP registration, SED child state R=0 at REDCON 4 and R=1 at REDCON 3, rig Thread discovery, synchronous REDCON transitions, direct D1=3.33 V at REDCON 3 matching LED/Office behavior, sed-current power shadow batteryMv=3968, corrected rig/device AWS IoT connectivity, and direct Sparkplug DCMD/accepted DDATA/confirmed DDATA/DDEATH/recovered DBIRTH captures. No Thread dataset TLVs were recorded.
<!-- SECTION:FINAL_SUMMARY:END -->

## Validation

<!-- SECTION:VALIDATION:BEGIN -->
Passed:

- `python3 -m unittest discover -s devices/common/mcu/xiao_mg24/tests`
- `python3 -m unittest discover -s devices/common/mcu/xiao_nrf54l15/tests`
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py devices/common/mcu/xiao_mg24/scripts/thread_factory.py devices/common/mcu/xiao_nrf54l15/scripts/redcon_nve.py`
- `python3 devices/common/mcu/xiao_mg24/scripts/thread_factory.py validate power-si-001 --dataset-tlvs tmp/power-si-test-dataset.hex`
- `python3 devices/common/mcu/scripts/stock_zephyr_mcu.py --device power-si thread-factory-hex power-si-001 tmp/power-si-test-dataset.hex --output tmp/power-si-thread-factory-test.hex`
- `python3 devices/common/mcu/scripts/stock_zephyr_mcu.py --device power-si build`
- `python3 devices/common/mcu/scripts/stock_zephyr_mcu.py --device power build`
- `go test ./...` from `rig/`
- `just --justfile rig/justfile build`
- `UV_CACHE_DIR=/Users/Maxim/Developer/txing/tmp/uv-cache uv run --project shared/aws/python pytest shared/aws/python/tests`
- `bun test` from `office/`
- `bun run build` from `office/`
- `git diff --check`
- `printf '0e080000000000010000000300001235\r\nDone\r\n' | awk '{ gsub(/[[:space:]]/, ""); if ($0 ~ /^[[:xdigit:]]+$/) { print; found=1 } } END { exit(found ? 0 : 1) }' > tmp/power-si-dataset-from-otctl-test.hex && python3 devices/common/mcu/xiao_mg24/scripts/thread_factory.py validate power-si-001 --dataset-tlvs tmp/power-si-dataset-from-otctl-test.hex`
- `just --list mcu && just --list power-si::mcu`
- `python3 - <<'PY' ... west_flash_command('power-si') ... west_flash_command('power-si', Path('factory.hex')) ... openocd_command('power', Path('factory.hex')) ... PY`
- Repository search for stale root `mcu::flash` instructions and the removed
  power-si factory-hex recipe returned no remaining docs/tooling matches.
- `python3 -m unittest devices.common.mcu.xiao_mg24.tests.test_thread_factory`
- `python3 -m py_compile devices/common/mcu/scripts/stock_zephyr_mcu.py devices/common/mcu/xiao_mg24/scripts/thread_factory.py`
- `python3 devices/common/mcu/scripts/stock_zephyr_mcu.py --device power-si thread-factory-hex power-si-001 tmp/power-si-test-dataset.hex --output tmp/power-si-thread-factory-test.hex`, verified generated HEX starts at `0x0817a000`.
- `python3 - <<'PY' ... west_flash_command('power-si') ... west_flash_command('power-si', Path('factory.hex')) ... openocd_command('power', Path('factory.hex')) ... PY`, verified the `power-si` commands use `west flash -r pyocd -- --pyocd /Users/Maxim/Developer/txing/devices/common/mcu/.venv/bin/pyocd` and the nRF command remains on the existing OpenOCD path.

The initial direct `python3 -m unittest discover -s shared/aws/python/tests` command failed because it bypassed the uv-managed package import path; the uv/pytest command above is the correct shared AWS validation harness and passed with 137 tests.

Host/tooling validation notes:

- Earlier `just mcu::install` failed when using Zephyr's documented `pyocd pack install --update EFR32MG24` shorthand because pyOCD requires an exact/glob part match. The installer now requests `EFR32MG24B220F1536IM48`, which resolves and installs the expected `SiliconLabs.GeckoPlatform_EFR32MG24_DFP.2025.12.1` pack.
- `just mcu::install`
- `just mcu::check`
- `pyocd pack show`, with repo-local MCU `HOME`, reports `SiliconLabs.GeckoPlatform_EFR32MG24_DFP 2025.12.1`.
<!-- SECTION:VALIDATION:END -->
