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
  `mRxOnWhenIdle=false` with full network data after SRP acceptance. Release
  and ordinary debug return to receiver-on bootstrap mode once per boot if that
  SED attachment fails, so the device remains discoverable while the upstream
  hardware blocker remains open. The `sed-debug` candidate profile instead
  enables a bounded SED-only recovery policy: it makes at most three SED retries
  after loss and never restores receiver-on mode. TASK-21.5 SED validation uses
  this explicit profile. It temporarily applies one isolated downstream
  candidate to the owning Silabs HAL checkout for the build only: an encrypted
  empty CCM message with a MIC derives its tag from B0 and formatted AAD with the
  existing RadioAES ECB primitive instead of the empty-payload CCM DMA
  descriptor. The candidate leaves the stock `IEEE802154_HW_TX_SEC` path,
  normal driver behavior, post-processing of emitted MICs, and retry behavior
  unchanged. It contains no logging and remains a downstream candidate until
  upstream accepts an equivalent fix.
  Hardware validation of the candidate shows accepted 5000 ms SED Data Polls,
  `RxErrSec: 0` after a fresh OTBR counter reset, active SRP, and successful
  queued indirect ICMPv6 delivery. It does not make the unmodified release/debug
  images a production SED path.
  Normal `build` and `build-debug` profiles keep unmodified Zephyr sources;
  release disables serial interfaces, while ordinary debug enables UART, shell,
  and OpenThread diagnostics. `sed-debug` is the only candidate SED profile. It
  enables Zephyr PM, initializes USART0 plus its PA8/PA9 pinctrl, retains the
  UART shell and diagnostics, and uses bounded SED-only recovery. Comparison
  with a separate output-silent profile showed no material sleep-phase
  difference once both images initialized those pins, so the redundant silent
  profile was removed.
  Hardware measurement established that USART0 initialization is required to
  drive the onboard SAMD11-facing UART connection: with an empty parent queue
  the measured sleep floor is about `0.04 mA`, versus about `0.3 mA` when the
  UART pins are uninitialized. Sustained indirect traffic with `QMsgCnt>0` also
  measures about `0.3 mA`; wait for `QMsgCnt=0` and the following data poll
  before recording idle current. Serial output can affect wake-phase activity,
  so current evidence must still be correlated with OTBR and a child row with
  `R=0`.
- REDCON: only levels `3` and `4`, with D1 as the active-high controlled output
  and the board LED following the same state.
- Factory data: `TXT1` written by
  `just mcu::nve <thing-name> <dataset-tlvs-file>` at `0x0817a000`. The final
  16 KiB of flash (`0x0817c000..0x0817ffff`) is reserved for Zephyr/OpenThread
  settings and must not contain factory data.
- State protocol: `GET /txing/v1/state` and `PUT /txing/v1/redcon` are served
  over Thread CoAP on port `5683`; SRP registers `_txing-coap._udp` with TXT
  records `type=power-si` and `pv=1`.
- Battery: the current MCU state response returns `batteryMv: null`; the rig
  only publishes a `power` battery shadow when the device supplies a value.
- Production firmware deliberately disables UART, console, shell, and log
  backends. Before production SED current acceptance, it must still initialize
  the onboard SAMD11-facing PA8/PA9 connection through USART0 or equivalent
  explicit pinctrl; the current unmodified release profile does not yet satisfy
  that measured board electrical requirement. Validate production attachment
  through SRP/DNS-SD and the rig, not serial output.

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
