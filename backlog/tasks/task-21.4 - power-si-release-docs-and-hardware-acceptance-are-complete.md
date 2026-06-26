---
id: TASK-21.4
title: power-si release docs and hardware acceptance are complete
status: In Progress
assignee:
  - '@Codex'
created_date: '2026-06-20 07:12'
updated_date: '2026-06-26 16:27'
labels: []
milestone: m-0
dependencies:
  - TASK-21.1
  - TASK-21.2
  - TASK-21.3
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
- [ ] #4 Manual acceptance evidence covers user-run factory provisioning, firmware flashing, SRP registration, rig discovery, REDCON 4/3 transitions, D1 output, battery shadow updates, and Sparkplug birth/data/death behavior.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect existing rig, MCU, shared AWS, and Office docs/tests to identify what TASK-21.4 must add beyond the implementation tasks.
2. Update durable docs for txing-thread-connectivity release/service coverage, OTBR prerequisites, power-si factory provisioning, manual flashing, dataset secrecy, and hardware acceptance evidence capture.
3. Run the relevant MCU, rig Go, shared AWS/Python, and Office validation commands that can run without hardware/AWS mutation.
4. Record validation and manual-acceptance status in Backlog, marking only criteria proven by current evidence.
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

TASK-21.4 AC #4 remains open. Still required: real rig DNS-SD discovery; rig CoAP GET state and REDCON 4/3 command confirmation; D1/LED measurements; Thread/power shadow evidence; and Sparkplug DBIRTH/DDATA/DDEATH evidence. The MCU currently reports `batteryMv: null`, so battery-shadow acceptance also requires battery measurement implementation before it can be demonstrated. The current Thread mode is receiver-on MTD, not a sleepy end device; its power behavior needs an explicit acceptance decision or SED implementation.
<!-- SECTION:NOTES:END -->

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
