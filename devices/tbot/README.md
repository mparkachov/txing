# TBot device

`tbot` is a new Thread-first device type for the Unit-equivalent board,
MCP, control, and video contract. Its XIAO nRF54LM20A Sense MCU uses the shared
stock Zephyr/OpenThread implementation with the `tbot` SRP service identity;
it has no BLE or Matter/CHIP firmware path.

## MCU contract

- Board: `xiao_nrf54lm20a/nrf54lm20a/cpuapp`
- Service: `_txing-coap._udp`, port `5683`, TXT `type=tbot`, `pv=1`
- CoAP: `GET /txing/v1/state`; `PUT /txing/v1/redcon` for transport levels `3`
  and `4`
- Thread: MTD sleepy end device with a `5000 ms` poll period. It starts and
  attaches in `rn`; after successful SRP registration and at REDCON 4 it uses
  `n`.
- Power output: XIAO D1 / SoC `P1.31` is active high for Raspberry Pi power;
  the blue `led0` follows the same transport state.
- REDCON 3: D1 and `led0` on, Thread mode `rn`.
- REDCON 4: D1 and `led0` off. The CoAP response is emitted before the bounded
  transition to Thread mode `n`.
- Battery: the nPM1300 is sampled on demand. A missing or failed reading is
  reported as `batteryMv: null`.

The board-side Thread adapter normalizes public TBot REDCON 1, 2, and 3 to
MCU transport REDCON 3; it sends MCU transport REDCON 4 only for public
REDCON 4. See the [architecture record](../../docs/history/architecture/tbot-thread-device-architecture.md)
for the full public capability contract.

## Manual provisioning and flashing

Do not commit Thread datasets: they are network credentials. Obtain the active
dataset TLVs from the already configured colocated OTBR and store them in an
ignored local file, for example `tmp/tbot-dataset.hex`.

```bash
sudo ot-ctl dataset active -x \
  | awk '{ gsub(/[[:space:]]/, ""); if ($0 ~ /^[[:xdigit:]]+$/) print }' \
  > tmp/tbot-dataset.hex

just mcu::install
just mcu::check
just tbot::mcu::nve tbot-001 tmp/tbot-dataset.hex
just tbot::mcu::build-sed-debug
just tbot::mcu::build
```

The commands intentionally prepare artifacts only. The operator chooses and
executes the manual programming step:

```bash
# Diagnostic hardware-acceptance image
just tbot::mcu::flash sed-debug

# Silent production image
just tbot::mcu::flash
```

After flashing, confirm the Thread child and matching SRP record from the OTBR,
then exercise the tbot REDCON controls through Office. Verify that REDCON 4
returns the child to receiver-off `n` mode within the five-second poll bound,
and that REDCON 3 turns on D1/P1.31 and `led0` before switching to `rn`.
Production firmware has serial, console, shell, and logging diagnostics
disabled; validate it through OTBR, the Thread adapter, and Office rather than
serial output.

Target-enclosure hardware acceptance remains a separate milestone task. Do not
ship a TBot until the specified antenna and enclosure demonstrate repeatable
Thread control, board boot/recovery, video, and motion-control acceptance.

## Board runtime

TBot uses the shared board daemon, KVS master, and motor hardware worker with
the `tbot` build identity. Its Thread adapter delivers the same public board,
MCP, active-control, motor-failsafe, and video behavior as Unit. Build and test
the board artifacts from the repository root:

```sh
just tbot::board::test
just tbot::board::hardware-test-native
just tbot::board::nerdctl-build
just tbot::board::nerdctl-smoke
```

The Alpine/OpenRC installation and maintenance runbook is shared with Unit;
set `TXING_DEVICE=tbot` and follow [Board](../../docs/components/board.md).
TBot binaries use the independent `tbot-v*` release stream:

```sh
just release::build tbot
```

## ArduPilot motor proof of concept

The optional ArduRover proof of concept is separate from the normal board
runtime. It starts from a disposable clean-upstream checkout and applies only
TBot-owned patches; do not reuse a checkout that carries another device's patch
stack.

```sh
just tbot::ardupilot::checkout
just tbot::ardupilot::patch
just tbot::ardupilot::test
just tbot::ardupilot::build
```

The defaults use upstream `MOT_PWM_TYPE=3`, left/right throttle functions, and
brushed-reverse relay functions on BCM GPIO 5 and 6. They deliberately leave
`MOT_PWM_FREQ` unset so its upstream 16 kHz default remains configurable through
MAVLink after restart. Installation and manual transfer of motor ownership are
covered by the separate optional-service milestone.

Release publication never upgrades a board automatically. On the board, an
operator installs the TBot daemon and hardware worker plus the shared KVS
master using the documented root-owned `mise` flow, verifies the services, and
restarts only the affected OpenRC services.
