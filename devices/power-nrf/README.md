# Power nRF device

`power-nrf` is the Thread-only Power device type for the Seeed XIAO
nRF54LM20A Sense running stock Zephyr.  It has the same `sparkplug`, `thread`,
and `power` shadow contract and REDCON 3/4 behavior as `power-si`; it has no
Matter/CHIP or BLE implementation.

## Release status: blocked by radio hardware acceptance

This device type must not be deployed in the target enclosure.  Hardware
testing on 2026-08-02 established that the XIAO nRF54LM20A Sense can attach and
register its SRP service only while its Thread receiver is on (`rn`) at very
short range.  After the required transition to the 5-second sleepy-end-device
mode (`n`), no indirect delivery/reachability within the CoAP test window was
validated, including at very short range.  Consequently REDCON, PMIC, and
Office end-to-end acceptance were not reached.

This was tested against the same OTBR and RF environment where `power-si`
operates.  Raising the XIAO nRF radio transmit power at runtime did not resolve
the receive-path failure and is not persistent across a reset.  The board
vendor documents this board as using an external IPEX4 antenna; that antenna
cannot fit in the target enclosure.  Treat the board/enclosure combination as
unsuitable for this product, rather than treating this as a deployable firmware
configuration.  See Seeed's [XIAO nRF54LM20A Sense guide](https://wiki.seeedstudio.com/xiao_nrf54lm20a_getting_started/).

To resume this work, select RF hardware that is compatible with the enclosure:
an enclosure-compatible external antenna, a module with a suitable integrated
2.4 GHz antenna, or a validated custom antenna design.  Repeat the complete
hardware acceptance below after that change.  Do not use the current result as
approval to enlist or ship a `power-nrf` device.

## Intended contract

- Board: `xiao_nrf54lm20a/nrf54lm20a/cpuapp`
- Service: `_txing-coap._udp`, port `5683`, TXT `type=power-nrf`, `pv=1`
- CoAP: `GET /txing/v1/state`; `PUT /txing/v1/redcon` for levels `3` and `4`
- Thread: MTD sleepy end device, `5000 ms` poll period; `rn` only for initial
  attach/SRP registration and REDCON 3
- REDCON 3: D1 and blue `led0` on, Thread `rn`
- REDCON 4: D1 and `led0` off; CoAP reply is sent before returning Thread to
  `n`
- Battery: on-demand nPM1300 measurement; unavailable or failed reads publish
  `batteryMv: null`

## Operator procedure (only after the hardware block is resolved)

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

4. Prepare Zephyr, generate the `TXN1` factory Intel HEX, and build the desired
   image.  Use `sed-debug` for first hardware acceptance.

   ```bash
   just mcu::install
   just mcu::check
   just power-nrf::mcu::nve power-nrf-001 tmp/power-nrf-dataset.hex
   just power-nrf::mcu::build-sed-debug
   ```

5. Manually program the factory HEX and firmware using the generated stock
   OpenOCD command.  Flashing is intentionally an operator action:

   ```bash
   just power-nrf::mcu::flash sed-debug
   ```

6. Verify the Thread child and SRP record from the OTBR, then exercise REDCON
   from Office.  The enlisted Thing's discovered TXT `type` must be exactly
   `power-nrf`.

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
| Child is non-router (`R=0`) | Observed during the successful attach |
| Steady-state `ot mode n` with a 5000 ms poll and reliable indirect delivery | Failed; no usable reachability after the transition to `n` |
| REDCON 3/4 output and `rn`/`n` transitions | Not accepted; requires reliable SED delivery |
| nPM1300 battery telemetry | Not accepted; requires reliable SED delivery |
| Office Thread/Power state and control | Not reached; blocked by the preceding failure |

An SRP registration alone is not acceptance: the rig must be able to deliver a
CoAP request to the sleepy child within the configured timeout, receive the
confirmed response, and retain the Thread capability.  A future hardware trial
must demonstrate that for REDCON 4, then prove REDCON 3 changes the child to
`rn` and D1/`led0` on, and that REDCON 4 returns it to `n` after the response.
