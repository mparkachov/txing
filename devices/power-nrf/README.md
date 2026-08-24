# Power nRF device

`power-nrf` is the Thread-only Power device type for the Seeed XIAO
nRF54LM20A Sense running the shared stock Zephyr/OpenThread implementation. It
has the same `sparkplug`, `thread`, and `power` shadow contract and REDCON 3/4
behavior as `power-si`; it has no Matter/CHIP or BLE implementation. Its
device-owned configuration preserves the `power-nrf` SRP service identity.

## Release status: bench and production behavior passed; enclosure validation outstanding

The target-enclosure release is not yet accepted.  Hardware testing without a
usable external antenna on 2026-08-02 established that the XIAO nRF54LM20A
Sense could attach and register its SRP service only while its Thread receiver
was on (`rn`) at very short range.  After the required transition to the
5-second sleepy-end-device mode (`n`), no indirect delivery/reachability within
the CoAP test window was validated, including at very short range.

This was tested against the same OTBR and RF environment where `power-si`
operates.  Raising the XIAO nRF radio transmit power at runtime did not resolve
the receive-path failure and is not persistent across a reset.  The board
vendor documents this board as using an external IPEX4 antenna.  See Seeed's
[XIAO nRF54LM20A Sense guide](https://wiki.seeedstudio.com/xiao_nrf54lm20a_getting_started/).

On 2026-08-22, an operator resumed the trial with an external antenna.  The
device registered on the OTBR, completed repeated REDCON 3/4 cycles from
Office, changed its physical outputs and Thread modes as specified, and
published live battery telemetry.  This passes the recorded bench checks.  On
2026-08-24, the operator rebuilt the production release, ran it on the device,
and confirmed the Office REDCON 4 to 3 to 4 transition worked as expected.  The
production smoke check therefore passes, but the antenna is not yet accepted
for the target enclosure.  Do not ship a `power-nrf` device until the intended
antenna fits and the same behavior is validated in the enclosure.

## Intended contract

- Board: `xiao_nrf54lm20a/nrf54lm20a/cpuapp`
- Service: `_txing-coap._udp`, port `5683`, TXT `type=power-nrf`, `pv=1`
- CoAP: `GET /txing/v1/state`; `PUT /txing/v1/redcon` for levels `3` and `4`
- Thread: MTD sleepy end device, `5000 ms` poll period; `rn` only for initial
  attach/SRP registration and REDCON 3
- Controlled output: header pin A1 (SoC GPIO `P1.31`), active-high.  Zephyr's
  stock board definition exposes this as `xiao_d` connector index 1 and calls
  it D1 internally; Seeed's current [pin map](https://wiki.seeedstudio.com/xiao_nrf54lm20a_getting_started/#pin-map)
  labels the physical pin A1.
- REDCON 3: A1 (`P1.31`) and blue `led0` on, Thread `rn`
- REDCON 4: A1 (`P1.31`) and `led0` off; CoAP reply is sent before returning
  Thread to `n`
- Battery: on-demand nPM1300 measurement; unavailable or failed reads publish
  `batteryMv: null`

## Operator procedure

1. Deploy the updated device catalog using the normal user-run AWS deployment
   flow, then enlist a `power-nrf` Thing to the target `raspi` rig.  Do not run
   these cloud mutations as part of firmware preparation.
2. On the colocated OTBR rig, install a rig release containing
   `txing-thread-connectivity`, enable it in
   `/root/.config/txing/rig-daemon/daemon.env`, and restart the Sparkplug and
   Thread-connectivity services.  Confirm both services and `otbr-agent` are
   active before flashing a device.
3. Obtain the active dataset as raw TLVs on the OTBR.  The TLVs are credentials:
   keep them in an ignored local file and never commit them.

   ```bash
   mkdir -p tmp
   sudo ot-ctl dataset active -x \
     | awk '{ gsub(/[[:space:]]/, ""); if ($0 ~ /^[[:xdigit:]]+$/) print }' \
     > tmp/power-nrf-dataset.hex
   ```

4. Prepare Zephyr and generate the `TXN1` factory Intel HEX.  Use `sed-debug`
   for initial hardware acceptance or diagnostics.  After those checks pass,
   build the production release with `build`; the release disables serial,
   console, shell, and logging diagnostics.

   ```bash
   just mcu::install
   just mcu::check
   just power-nrf::mcu::nve power-nrf-001 tmp/power-nrf-dataset.hex

   # Diagnostic hardware-acceptance image
   just power-nrf::mcu::build-sed-debug

   # Production release image
   just power-nrf::mcu::build
   ```

5. Manually flash the selected firmware profile.  Omitting the profile selects
   the production release.  Flashing is intentionally an operator action:

   ```bash
   # Diagnostic hardware-acceptance image
   just power-nrf::mcu::flash sed-debug

   # Production release image (default profile)
   just power-nrf::mcu::flash
   ```

6. Verify the Thread child and SRP record from the OTBR, then exercise REDCON
   from Office.  The enlisted Thing's discovered TXT `type` must be exactly
   `power-nrf`.  After flashing the production image, repeat the SRP, Thread
   mode, REDCON output, Office state, and battery smoke checks; validate the
   silent production image through OTBR and Office rather than serial logs.

   ```bash
   sudo ot-ctl child table
   sudo ot-ctl srp server service
   sudo journalctl -u txing-thread-connectivity.service \
     -u txing-sparkplug-manager.service -n 200 --no-pager
   ```

## Hardware acceptance record

| Check | Result on 2026-08-02 |
| --- | --- |
| `TXN1` factory record and matching Thread dataset | Passed |
| Attach and SRP `_txing-coap._udp` registration in temporary `rn` mode | Passed at very short range |
| Child has its receiver off while idle (`R=0`) | Observed during the successful attach |
| Steady-state `ot mode n` with a 5000 ms poll and reliable indirect delivery | Failed; no usable reachability after the transition to `n` |
| REDCON 3/4 output and `rn`/`n` transitions | Not accepted; requires reliable SED delivery |
| nPM1300 battery telemetry | Not accepted; requires reliable SED delivery |
| Office Thread/Power state and control | Not reached; blocked by the preceding failure |

Current external-antenna trial evidence:

| Check | Result |
| --- | --- |
| Active SRP `_txing-coap._udp` registration | Passed: port `5683`, TXT `type=power-nrf` and `pv=1` |
| Office REDCON 3/4 command delivery | Passed |
| REDCON 4 Thread link mode | Passed: OTBR child flags `R=0`, `D=0`, `N=1`, which represent `ot mode n` |
| REDCON 4 to 3 indirect delivery | Passed once in approximately 4 seconds: `QMsgCnt` drained from 1 to 0 within the expected 5-second poll window |
| REDCON 3 Thread link mode and outputs | Passed: child flags changed to `R=1`, `D=0`, `N=1` (`ot mode rn`), A1 (`P1.31`) was high, and blue `led0` was on |
| Repeatable 5000 ms sleepy-mode delivery | Passed: after the initial approximately 4-second delivery, two additional REDCON 4 to 3 to 4 cycles succeeded |
| REDCON 3 to 4 response, mode, and outputs | Passed: Office showed Power disabled, A1 (`P1.31`) was low, blue `led0` was off, and child flags returned to `R=0`, `D=0`, `N=1` with `QMsgCnt=0` |
| nPM1300 battery telemetry | Passed: the Office detail panel showed `4174 mV` in REDCON 3 |
| Production release image | Passed on 2026-08-24: the production release was rebuilt, run on the device, and its Office REDCON 4 to 3 to 4 transition worked as expected |
| Intended antenna in the target enclosure | Not yet accepted |

The remaining acceptance work is to confirm that the intended antenna fits and
that the accepted behavior remains reliable in the target enclosure.
