# MCU

Firmware covers the XIAO nRF54L15 BLE targets (`unit`, `power`, and `weather`)
and the XIAO MG24 Thread target (`power-si`). These are separate board and
transport stacks that share the stock Zephyr workspace and MCU command surface.

## nRF Shared Stack Invariant

The nRF MCU firmware targets are `devices/unit/mcu`, `devices/power/mcu`, and
`devices/weather/mcu`. `devices/template/mcu` is only a scaffold and does not
build firmware.

All nRF MCU targets use the same shared stack:

- each target's `zephyr/CMakeLists.txt` sets `TXING_XIAO_NRF54L15_DIR` to
  `devices/common/mcu/xiao_nrf54l15`
- each target compiles `${TXING_XIAO_NRF54L15_DIR}/src/redcon.c`
- each target includes `${TXING_XIAO_NRF54L15_DIR}/include`
- shared setup and factory/NVE actions run through root `mcu` recipes backed by
  `devices/common/mcu/scripts/stock_zephyr_mcu.py`
- each target's `justfile` keeps device-owned `build`, `flash`, and `clean`
  recipes
- the shared `mcu::nve` recipe uses
  `devices/common/mcu/xiao_nrf54l15/scripts/redcon_nve.py`

Device-specific behavior belongs in the local `src/main.c` hooks passed through
`struct txing_redcon_ops`, local `zephyr/prj.conf`, and local devicetree
overlays. The shared REDCON implementation remains single-source: active XIAO
nRF54L15 targets share `redcon.c`, the REDCON UUID/payload handling, and the
common stock Zephyr install/build path.

## nRF Current Behavior

- target board: `xiao_nrf54l15/nrf54l15/cpuapp`
- firmware stack: stock Zephyr through `devices/common/mcu/zephyr`; the shared
  workspace currently defaults to `main` and can be overridden with
  `TXING_ZEPHYR_VERSION`
- shared stock Zephyr build driver:
  `devices/common/mcu/scripts/stock_zephyr_mcu.py`
- shared REDCON app entrypoint: `txing_redcon_run(&ops)`
- D1 / `gpio1 5` is the active-high enable for app hardware
- reset default: `REDCON 4`, D1 off, LED off, load regulators disabled, ADC suspended
- `REDCON 1`, `2`, and `3`: D1/LED on, state reported, battery sampled/notified, periodic active battery reports
- `REDCON 4`: D1 off, BLE remains connected when possible, idle battery reports every `60 s`, advertising resumes after disconnect
- REDCON GATT command writes support write-without-response; firmware validates
  the two-byte payload, records the accepted target state, and runs queued
  wake/sleep side effects after the command is accepted
- `unit` accepts REDCON `1`/`2`/`3`/`4` and preserves the current REDCON level across BLE disconnect
- `power` accepts REDCON `3`/`4` and preserves REDCON `3` across BLE disconnect
- `weather` accepts REDCON `4` idempotently, rejects other command levels, and exposes the weather measurement characteristic
- factory/NVE record at `0x000f0000` stores the AWS Thing ID used as the BLE
  advertised identity name with the `TXR1` layout

The integration contract is [devices/unit/docs/device-rig-shadow-spec.md](../../devices/unit/docs/device-rig-shadow-spec.md).

## Power SI XIAO MG24

`power-si` is a separate stock Zephyr/OpenThread application at
`devices/power-si/mcu` for board `xiao_mg24`. It uses the stock Silabs
IEEE 802.15.4 driver available from the shared Zephyr `main` workspace, CoAP
over Thread, and no Matter/CHIP stack.

- Thread role: MTD Sleepy End Device, not a router. The firmware builds with
  stock Zephyr/OpenThread SED support and uses a `5000 ms` poll period so rig
  CoAP commands have bounded sleepy-device latency. On XIAO MG24, startup uses
  a temporary receiver-on SRP bootstrap mode for reliable attach and service
  registration, then updates the attached child into steady-state
  `mRxOnWhenIdle=false` with full network data after SRP acceptance. The final
  release and `sed-debug` profiles enable a bounded SED-only recovery policy:
  each makes at most three SED retries after loss and never restores receiver-on
  mode. Ordinary debug retains the one-time receiver-on fallback for diagnosis.
  The final release and `sed-debug` profiles temporarily apply one isolated downstream
  candidate to the owning Silabs HAL checkout for the build only: an encrypted
  empty CCM message with a MIC derives its tag from B0 and formatted AAD with the
  existing RadioAES ECB primitive instead of the empty-payload CCM DMA
  descriptor. The candidate leaves the stock `IEEE802154_HW_TX_SEC` path,
  normal driver behavior, post-processing of emitted MICs, and retry behavior
  unchanged. It contains no logging and remains a downstream candidate until
  upstream accepts an equivalent fix.
  Hardware validation of the candidate shows accepted 5000 ms SED Data Polls,
  `RxErrSec: 0` after a fresh OTBR counter reset, active SRP, and successful
  queued indirect ICMPv6 delivery. The final release is the production SED
  path; it applies the candidate only during the build and leaves upstream
  sources unchanged afterward. Ordinary debug remains an unmodified Zephyr
  diagnostic image. `sed-debug` retains the same candidate and functional
  overlay with UART, shell, and PM diagnostics. The silent release overlay
  disables console, shell, logging, and application diagnostics while retaining
  the validated SED behavior. A temporary PM,
  RAIL, and ACK diagnostic experiment confirmed EM2 residency but did not
  identify a causal or safe corrective change; its isolated patches and profile
  were removed on 2026-07-20.
  All power figures recorded before 2026-07-20 are invalid because the meter
  was in AC-current mode. Use only DC-current measurements with USB
  disconnected, and record the OTBR child `R` flag and `QMsgCnt` alongside each
  result. Latest DC observations were approximately `16-20 mA` in both SED
  `n` and receiver-on `rn` states, so no low-current conclusion is accepted.
- REDCON: only levels `3` and `4`, with D1 as the active-high controlled output
  and the board LED following the same state. The final release and `sed-debug`
  use a live Thread link-mode policy: REDCON `3` requests receiver-on MTD
  (`rn`) for immediate follow-up control, while REDCON `4` replies before a
  bounded 100 ms grace then returns to sleepy MTD (`n`).
- Factory data: `TXT1` written by
  `just mcu::nve <thing-name> <dataset-tlvs-file>` at `0x0817a000`. The final
  16 KiB of flash (`0x0817c000..0x0817ffff`) is reserved for Zephyr/OpenThread
  settings and must not contain factory data.
- State protocol: `GET /txing/v1/state` and `PUT /txing/v1/redcon` are served
  over Thread CoAP on port `5683`. The version-1 PUT body is
  `{"version":1,"redcon":3}` or `{"version":1,"redcon":4}`. SRP registers
  `_txing-coap._udp` with TXT records `type=power-si` and `pv=1`.
- Battery: the final release samples the XIAO MG24 battery divider on demand using
  active-high PD3 enable, a 30 ms settling interval, and the PD4 IADC input with
  the calibrated internal 1.21 V reference at 0.5x gain, then reports twice the
  divider voltage as `batteryMv`. Ordinary debug and `sed-debug` continue to
  return `batteryMv: null`. The rig only publishes a `power` battery
  shadow when the device supplies a value; sampling failure remains `null`
  rather than a fabricated zero.
- Production firmware deliberately disables UART, console, shell, and log
  backends. The prior claim that its USART0/PA8/PA9 initialization determined
  SED current was based on invalid AC-current readings and is withdrawn. Validate
  the final release through SRP/DNS-SD and the rig, not serial output.

See [devices/power-si/README.md](../../devices/power-si/README.md) for OTBR
prerequisites, provisioning, manual flashing, and hardware acceptance steps.

## Build Artifacts

Run from the repo root:

```bash
just mcu::install
just mcu::check
just unit::mcu::build
just power::mcu::build
just weather::mcu::build
just power-si::mcu::build
just power-si::mcu::build-sed-debug
```

Or from `devices/unit/mcu/`:

```bash
just build
```

## Flashing

Firmware flashing and NVE programming remain manual user actions. Firmware
flashing is device-owned; factory/NVE programming is shared:

```bash
just unit::mcu::flash
just power::mcu::flash
just weather::mcu::flash
just power-si::mcu::flash
just power-si::mcu::flash debug
just power-si::mcu::flash sed-debug
just mcu::nve <thing-name>
just mcu::nve <thing-name> <dataset-tlvs-file>
```

The one-argument NVE command preserves the nRF `TXR1` behavior. The
two-argument form provisions `power-si` TXT1 factory data.

Current runner split:

- XIAO nRF54L15 targets use the stock Zephyr OpenOCD runner over the onboard
  CMSIS-DAP debugger.
- XIAO MG24 (`power-si`) uses the stock Zephyr pyOCD runner over the onboard
  CMSIS-DAP debugger, with `mcu::install` installing the repo-local pyOCD
  binary and requesting the EFR32MG24B220F1536IM48 CMSIS target pack.
