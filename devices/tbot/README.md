# TBot device

`tbot` is a new Thread-first device type for the Unit-equivalent board,
MAVLink, control, and video contract. Its XIAO nRF54LM20A Sense MCU uses the shared
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

## Board runtime and MAVLink contract

TBot's catalog contract declares `mavlink`, not `mcp`, with an independent
`<thing>-mavlink` WebRTC data channel and the REDCON 1 `mavlinkArmed` input.
Its descriptor, status, named-shadow schema, defaults, and fixtures are owned
under `devices/tbot/aws/`; the shared WebRTC and local APIs are documented in
[Board MAVLink capability contract](../../docs/contracts/board-mavlink.md).

The forward-only runtime cutover deploys this contract only with the coordinated
TBot release, catalog/IAM application, re-enlistment, and fresh board bundle.

### Cloud catalog rollout

Cloud catalog provisioning is forward-only and does not start or arm the rover.
When the coordinated runtime release is available, the operator applies the
catalog, re-enlists the existing TBot using its existing rig and device name,
and creates a fresh board bundle:

```sh
: "${RIG_THING_ID:?set the existing raspi rig Thing ID}"
: "${THING_ID:?set the existing TBot Thing ID}"
just aws::deploy
just aws::deploy-device "$RIG_THING_ID" tbot "$THING_ID"

# aws::cert refuses to overwrite local material: move the old local bundle
# aside first, then create and install the fresh bundle by the board runbook.
just aws::cert "$THING_ID"
```

Re-enlistment preserves existing named-shadow payloads and creates only a
missing `mavlink` shadow. The fresh daemon certificate policy grants master
access to exactly `<thing>-board-video` and `<thing>-mavlink`; Office retains
viewer-only Kinesis Video permissions. After the runtime is proven in service,
an operator must manually delete the legacy named `mcp` shadow. Do not remove
it before the MAVLink runtime cutover is verified, and no deploy or enlistment
operation deletes it automatically.

TBot uses the shared board daemon and KVS master with TBot-derived MAVLink
identities. ArduPilot exclusively owns the DRV8835; `txing-tbot-mavlink` owns
the loopback flight-controller connection; the daemon remains the only owner
of control sessions, epochs, leases, REDCON, and retained state. The KVS master
starts its `<thing>-mavlink` data peer independently of video. There is no TBot
MCP, hardware-worker, or automatic fallback path. Build and test the current
board artifacts from the repository root:

```sh
just tbot::board::test
just tbot::board::mavlink-build-alpine
just tbot::board::nerdctl-build
just tbot::board::nerdctl-smoke
```

Follow the [TBot MAVLink runtime](../../docs/components/board.md#tbot-mavlink-runtime)
runbook for Alpine/OpenRC installation and cutover. TBot binaries use the
independent `tbot-v*` release stream:

```sh
just release::build tbot
```

The `tbot-v0.18.7` release publishes `txing-tbot-daemon`,
`txing-tbot-mavlink`, and `txing-tbot-ardupilot` assets. The ArduPilot archive
contains `txing-tbot-ardupilot` and
`txing-tbot-ardupilot.defaults.parm`; its matching
`txing-tbot-ardupilot-source.tar.gz` contains the exact patched upstream source,
initialized submodules, license, and upstream build instructions. The release
notes record the upstream commit SHA. It does not publish a TBot hardware-worker
asset. Install all four runtime services, including the matching shared KVS
release, together by the [Board runbook](../../docs/components/board.md#tbot-mavlink-runtime).

## ArduPilot motor implementation

The ArduRover implementation is the normal TBot motor runtime. It starts from a
disposable clean-upstream checkout and applies only TBot-owned patches; do not
reuse a checkout that carries another device's patch stack.

```sh
just tbot::ardupilot::checkout
just tbot::ardupilot::patch
just tbot::ardupilot::test
just tbot::ardupilot::build
```

The defaults use upstream `MOT_PWM_TYPE=3`, left/right throttle functions, and
brushed-reverse relay functions on BCM GPIO 5 and 6. The small TBot patch
claims those two direction lines through `/dev/gpiochip0`, using the same Linux
GPIO character-device API as the hardware worker; it deliberately does not use
ArduPilot's legacy Raspberry Pi `/dev/mem` GPIO mapper. They deliberately leave
`MOT_PWM_FREQ` unset so its upstream 16 kHz default remains configurable through
MAVLink after restart. Its OpenRC service binds `SERIAL1` only at
`udpin:127.0.0.1:14550`, so no direct LAN/QGroundControl endpoint is exposed.
The MAVLink cutover and exclusive motor ownership are covered by the
[Board runbook](../../docs/components/board.md#tbot-mavlink-runtime).

Release publication never upgrades a board automatically. On the board, an
operator installs TBot daemon, MAVLink, ArduPilot/defaults, and the shared KVS
master as one compatible set using the documented root-owned `mise` flow,
verifies the services, and restarts them in ownership order.
