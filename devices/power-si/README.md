# Power SI Device

`power-si` is a raspi-compatible txing power device type for Seeed XIAO MG24
hardware running stock Zephyr/OpenThread. It has the same product-level REDCON
and power-shadow behavior as `power`, but uses Thread instead of BLE.

This device type is Thread-only. Matter commissioning, clusters, and fabrics are
out of scope for this milestone.

## Contract

- Capabilities: `sparkplug`, `thread`, `power`
- REDCON command levels: `4`, `3`
- REDCON `4` requires `sparkplug` and `thread`
- REDCON `3` requires `sparkplug`, `thread`, and `power`
- Named shadows: `sparkplug`, `thread`, `power`

The Thread CoAP service uses protocol version `1`. `GET /txing/v1/state`
returns `version`, `thingName`, `redcon`, and `batteryMv`. `PUT
/txing/v1/redcon` requires JSON content with both a numeric version and target
level, for example `{"version":1,"redcon":3}` or
`{"version":1,"redcon":4}`. The final release samples the XIAO MG24
battery divider on demand for both responses: PD3 enables the divider, the
firmware waits 30 ms for it to settle, and PD4 is sampled using the calibrated
1.21 V internal IADC reference at 0.5x gain. The divider voltage is multiplied
by two. The diagnostic profiles continue to return `batteryMv: null`.

## Rig Prerequisites

`power-si` requires a `raspi` rig running the three rig daemons documented in
[Rig](../../docs/components/rig.md):

- `txing-sparkplug-manager`
- `txing-thread-connectivity`
- `txing-ble-connectivity`

The Thread daemon does not install or configure OTBR. It reads the OTBR's local
SRP registry through `ot-ctl`; the OTBR and Thread daemon must therefore run on
the same rig host. The default SRP domain is `default.service.arpa`; override
`TXING_THREAD_SERVICE_DOMAIN` only when the OTBR network uses a different
domain.

Run these checks on the rig before expecting `txing-thread-connectivity` to
discover a device:

```bash
systemctl status --no-pager -l txing-thread-connectivity.service otbr-agent.service
ot-ctl srp server service
```

The host DNS resolver and mDNS publication are not part of discovery. The
active `power-si._txing-coap._udp.default.service.arpa.` record from `ot-ctl`
is the direct source of truth. An unavailable OTBR control socket is a bounded
Thread daemon failure, not a service crash.

## SED Debug Rig And Office Acceptance

Use `sed-debug` for the first end-to-end REDCON test. Before starting, the
`power-si` Thing must already be enlisted to the target `raspi` rig, and the
rig must have installed a `rig-v*` release that contains
`txing-thread-connectivity`. An OTBR SRP registration and an enabled
environment variable alone cannot update Office: the installed Thread daemon
and updated Sparkplug manager publish the capability state and Sparkplug birth
data that Office reads.

Verify the installed release and service before enabling it:

```bash
/root/.local/share/mise/installs/txing-thread-connectivity/latest/txing-thread-connectivity --version
sudo systemctl cat txing-thread-connectivity.service
sudo grep -E '^export TXING_(SPARKPLUG_MANAGER|THREAD_CONNECTIVITY)_ENABLED=' \
  /root/.config/txing/rig-daemon/daemon.env
```

If the binary or systemd unit is absent, publish and install the current rig
release first, following the [Rig release instructions](../../docs/components/rig.md#upgrade).
Then enable the daemon in the rig configuration:

```bash
sudo sed -i.bak 's/^export TXING_THREAD_CONNECTIVITY_ENABLED=.*/export TXING_THREAD_CONNECTIVITY_ENABLED=true/' \
  /root/.config/txing/rig-daemon/daemon.env
sudo systemctl restart txing-sparkplug-manager.service txing-thread-connectivity.service
sudo systemctl status --no-pager -l txing-sparkplug-manager.service txing-thread-connectivity.service
```

Build and manually flash the already provisioned SED test firmware. Do not
reprogram `TXT1` unless the Thing name or Thread dataset changed:

```bash
just power-si::mcu::build-sed-debug
just power-si::mcu::flash sed-debug
```

After the device has attached in SED mode and SRP is active, verify both the
device/OTBR evidence and the rig path:

```bash
sudo ot-ctl child table
sudo ot-ctl srp server service
sudo journalctl -u txing-thread-connectivity.service -u txing-sparkplug-manager.service \
  -n 200 --no-pager
```

At initial REDCON 4, the child row must remain `R=0`; the service must be
`deleted:false` on port `5683` and include the test-only TXT value
`profile=sed-debug` (shown by `ot-ctl` as
`profile=7365642d6465627567`). The Thread daemon must have reconciled the
enlisted device and must not report CoAP discovery or polling failures. Within
one Thread poll/discovery cycle, open the Thing in Office: it is registered
when the Sparkplug state is live, `thread` is shown active, and the REDCON ring
reflects the CoAP state.

The `sed-debug` profile alone tests active-power link policy. Use the Office
REDCON control to command `3`: the device applies D1/LED state, changes its
attached Thread child to receiver-on MTD (`ot mode` reports `rn` and OTBR shows
`R=1`), then returns the confirmed CoAP state. The Thread daemon logs:

```text
Thread REDCON command received thing=<thing-name> command=<command-id> redcon=3
Thread sed-debug REDCON transition confirmed thing=<thing-name> redcon=3 requestedLinkMode=rn
```

Record the journal timestamps for those two entries while the device is in
REDCON 4 / `ot mode n`. Their difference must be no more than one `5000 ms`
child poll plus bounded processing margin; retain the two timestamped lines in
the task or release acceptance record. Repeat the same capture for REDCON `3`
to `4`; receiver-on behavior should be immediate apart from processing margin.

Command `4` next. The device returns to sleepy MTD (`ot mode` reports `n` and
OTBR shows `R=0`) and the daemon logs `requestedLinkMode=n`. SRP must remain
active throughout both live link-mode updates; there must be no new child
attach or SRP registration. Each command uses the existing synchronous
Sparkplug DCMD to local IPC to Thread CoAP path; allow up to the configured
`12000 ms` Thread CoAP timeout. Confirm the final state in Office, the
`power-si` D1 output, the board LED, and the OTBR child row. A command timeout
or loss of `thread` capability is a failed SED runtime test, not an Office-only
problem. Release and ordinary `debug` profiles do not advertise
`profile=sed-debug` and do not change Thread link mode in response to REDCON.

For `sed-debug`, REDCON `4` keeps the receiver on for a bounded `100 ms`
response grace after the CoAP changed-state reply, then enters `n`. This lets
the rig receive synchronous confirmation before the child becomes sleepy; it
does not change the 5000 ms poll period or the final REDCON 4 link policy.

## Factory Data

`power-si` stores a versioned `TXT1` factory record in the XIAO MG24 factory
partition. The record contains:

- Thing name
- Thread Active Operational Dataset TLVs
- CoAP port, normally `5683`
- CRC

The factory record is stored at `0x0817a000`. Zephyr/OpenThread settings use
`0x0817c000..0x0817ffff` as a 16 KiB NVS area, because MG24 flash has 8 KiB
erase blocks and Zephyr NVS requires at least two sectors. This uses one erase
block from the board's unused secondary image slot.

Real Thread dataset TLVs are credentials. Do not commit them, paste them into
Backlog tasks, or store them under version control. Use a local ignored path
such as `tmp/power-si-dataset.hex` or another operator-controlled secret
location. Recording a short non-secret source label, timestamp, or OTBR/network
name in acceptance notes is fine; recording the TLVs is not.

On the OTBR, `ot-ctl dataset active` shows the active dataset in a
human-readable form. Use it to confirm that the OTBR is on the expected Thread
network:

```bash
sudo ot-ctl dataset active
```

The factory tool needs the same active dataset as raw Thread TLVs. Generate the
hex input file with `-x` and keep only the hex line, not the trailing `Done`
line:

```bash
mkdir -p tmp
sudo ot-ctl dataset active -x \
  | awk '{
      gsub(/[[:space:]]/, "");
      if ($0 ~ /^[[:xdigit:]]+$/) { print; found=1 }
    } END { exit(found ? 0 : 1) }' \
  > tmp/power-si-dataset.hex
```

Do not feed the human-readable `ot-ctl dataset active` output into the factory
tool. It must receive the TLV hex produced by `ot-ctl dataset active -x`.

Prepare the shared stock Zephyr workspace once:

```bash
just mcu::install
just mcu::check
```

Validate the dataset TLV file before programming factory data:

```bash
python3 devices/common/mcu/xiao_mg24/scripts/thread_factory.py validate \
  power-si-001 \
  --dataset-tlvs tmp/power-si-dataset.hex
```

Program the `TXT1` factory record with the shared NVE command:

```bash
just mcu::nve power-si-001 tmp/power-si-dataset.hex
```

## Firmware Build

Build the stock Zephyr/OpenThread firmware from the repository checkout:

```bash
just power-si::mcu::build
```

The expected firmware HEX is:

```text
devices/power-si/mcu/build/zephyr-xiao_mg24/zephyr/zephyr.hex
```

The build uses the repository's stock Zephyr workflow, currently defaulting to
Zephyr `main` for XIAO MG24 IEEE 802.15.4 radio support. The firmware starts
with D1 off and the board LED following the REDCON/power state. It will not
start Thread, CoAP, or SRP services until valid `TXT1` factory data is present.
The application builds as a stock Zephyr/OpenThread MTD Sleepy End Device with
a `5000 ms` poll period. On XIAO MG24, the firmware uses a temporary
receiver-on SRP bootstrap mode so the current Zephyr/Silabs stack can attach and
complete SRP registration reliably; after SRP acceptance it updates the attached
child into the intended steady-state SED posture with `mRxOnWhenIdle=false`, MTD
mode, full network data, and the same `5000 ms` poll period. The firmware also
restores OpenThread's `5504 us` receive-after-TX window because Zephyr's Silabs
S2 default currently sets it to `0`, which can break rx-off data-poll responses.
Rig Thread REDCON commands remain synchronous; the default rig CoAP timeout is
`12000 ms` so a command can wait for one sleepy poll window plus network jitter.

Current XIAO MG24 SED hardware evidence shows stock Zephyr/Silabs hardware MAC
TX security fails the secured zero-payload sleepy MAC Data Request path, so the
child does not receive the indirect response it needs to remain attached. A
hardware ACK with the frame-pending bit is not proof that the parent accepted
the Thread MAC security: the radio can send that ACK before the parent evaluates
the packet. The final release and `sed-debug` apply one isolated patch to the
owning Silabs HAL checkout only while building, then reverse it before the build
exits. The candidate bypasses the
RadioAES CCM dummy-payload descriptor only for encrypted empty messages with a
MIC. It builds the empty-message CCM tag from B0 and formatted AAD with the
existing RadioAES ECB primitive. It preserves hardware TX security and makes no
change to the IEEE 802.15.4 driver, post-processing of emitted MICs, retry state,
frame counters, decryption, CCM-star messages without a tag, or nonempty
payloads. It is a focused downstream candidate for upstream review.

Hardware validation of the candidate completed on XIAO MG24: after the SED
transition, fresh OTBR counters recorded accepted five-second Data Polls with
`RxErrSec: 0`; three queued ICMPv6 requests were delivered and replied to
within the 10-second test timeout; and the device remained `child` in `ot mode
n` with a `5000 ms` poll period. The same validated SED path is now the final
release image. The candidate remains a focused downstream change until upstream
accepts an equivalent fix.

### Firmware Profiles

| Profile | Command | Source and runtime policy | Intended use |
| --- | --- | --- | --- |
| Release | `just power-si::mcu::build` | Validated SED overlay and isolated RadioAES candidate, applied only during the build; console, shell, logging, and application diagnostics disabled; on-demand PD3/PD4 battery sampling enabled. | Final product firmware and Office/LED REDCON acceptance. |
| Debug | `just power-si::mcu::build-debug` | Unmodified stock Zephyr with UART, shell, and OpenThread diagnostics; ordinary receiver-on recovery remains available. | General firmware and Thread diagnosis. |
| SED debug | `just power-si::mcu::build-sed-debug` | Isolated RadioAES candidate applied only for the build; UART/shell, Zephyr PM, tickless idle, PM transition diagnostics, bounded requested-link recovery, and REDCON 3/4 `rn`/`n` link-policy testing. | SED functional, recovery, indirect-delivery, and active-power link-policy diagnosis. |

The release and `sed-debug` profiles reverse the candidate patch before the
build helper exits, so the shared Zephyr and Silabs HAL checkouts remain stock
after every build.

Build a serial/shell functional SED test image:

```bash
just power-si::mcu::build-sed-debug
```

The expected debug SED test HEX is:

```text
devices/power-si/mcu/build/zephyr-xiao_mg24-sed-debug/zephyr/zephyr.hex
```

`sed-debug` enables Zephyr PM and tickless operation while retaining the UART
shell and diagnostics. Use it for functional SED diagnosis. The silent final
release preserves the same SED and REDCON behavior without serial output and
adds on-demand battery reporting.

### Measurement Correction (2026-07-20)

All current figures recorded before this correction are invalid. The Brymen
BM235 was set to AC-current mode, so readings such as `0.04 mA` and `0.3 mA`
were not DC supply-current measurements and must not be used as acceptance or
design evidence. Those observations are retained in TASK-21.5 history for
traceability only. No conclusion about UART pins, queued Thread traffic, or
idle SED current may be drawn from them.

The subsequent DC-current investigation remains inconclusive. The functional
SED profile registered SRP, remained an OTBR child with `R=0`, and delivered
queued traffic at the expected bounded latency. The temporary PM/RAIL/ACK
diagnostics confirmed multi-second EM2 residency, but also observed transient
HF-clock-preservation requests and radio activity without identifying a causal
or safe corrective change. Those isolated diagnostic patches and the
`sed-pm-debug` profile were removed on 2026-07-20. The latest DC multimeter
observations were approximately `16-20 mA` in both SED `n` and receiver-on
`rn` states, so no low-current acceptance claim is made.

## Manual Flashing

Agents must not flash hardware. The operator flashes firmware with
`just power-si::mcu::flash` and programs factory data with `just mcu::nve`.
Both commands use Zephyr's stock `west flash` path with the `pyocd` runner over
the XIAO MG24 onboard CMSIS-DAP debugger.
This procedure does not require J-Link.

Run `just mcu::install` before flashing. It installs Zephyr's Python runner
requirements into the repository-local MCU virtualenv, refreshes pyOCD's CMSIS
pack index, and requests the EFR32MG24B220F1536IM48 pyOCD CMSIS target pack.
The `power-si` flash path explicitly passes the repo-local pyOCD binary to
Zephyr's pyOCD runner. `just mcu::check` verifies that pyOCD can see the
EFR32MG24B220F1536IM48 target before any firmware or factory flash command is
run.

Flash the already-built firmware:

```bash
just power-si::mcu::flash
```

Profile-specific firmware flashing uses the already-built HEX for that profile:

```bash
just power-si::mcu::flash debug
just power-si::mcu::flash sed-debug
```

The flash recipe does not rebuild. It passes the selected profile's HEX path
explicitly to pyOCD; verify that the command prints the requested profile path,
such as `zephyr-xiao_mg24-sed-debug/zephyr/zephyr.hex`, before flashing.
Re-run the matching `build*` command after source or configuration changes
before flashing a profile.

If this board previously received an older `power-si` factory image at
`0x0817c000`, erase the new settings range once before testing this firmware.
Leaving the old `TXT1` bytes there can make Zephyr NVS fail before application
logs start:

```bash
env \
  HOME="$(pwd)/devices/common/mcu/.home" \
  XDG_CACHE_HOME="$(pwd)/devices/common/mcu/.home/.cache" \
  devices/common/mcu/.venv/bin/pyocd erase \
  --target efr32mg24b220f1536im48 \
  --sector \
  0x0817c000-0x08180000
```

Program the `TXT1` factory record after generating the dataset TLV file:

```bash
just mcu::nve power-si-001 tmp/power-si-dataset.hex
```

## Production SRP Test

The SRP server does not provide an administrative delete command for a device
registration. Remove the existing registration through the currently running
debug firmware, so the device signs and sends the required SRP unregistration.
At the XIAO MG24 shell, while it is attached to Thread, run:

```text
ot srp client host remove 1 1
```

The first `1` removes the key lease and the second forces an unregistration
update even if the client no longer considers its host registered. Confirm the
server received it before flashing production firmware:

```bash
sudo ot-ctl srp server service
sudo ot-ctl srp server host
```

The `power-si._txing-coap._udp.default.service.arpa.` entry should be present
with `deleted: true`. Do not use `ot srp client host clear` for this test: it
only clears local state and does not notify the server.

Build and flash the release image, then program the factory record after the
firmware so the final device state contains both images:

```bash
just power-si::mcu::build
just power-si::mcu::flash
just mcu::nve power-si-001 tmp/power-si-dataset.hex
```

Wait for the device to attach and register, then run the same two OTBR commands.
The service must return to `deleted: false` with port `5683`, TXT values
`type=power-si` and `pv=1`, and the device's current mesh-local address. This
proves the production image read `TXT1` from flash and completed a fresh SRP
registration without the debug-only compiled factory data.

Production firmware intentionally emits no UART logs. A silent serial port
after reset is expected; use the SRP/DNS-SD result above, followed by rig CoAP
and shadow evidence, as the production validation signal.

## Thread Attach Debugging

If the OTBR `child table` does not show the XIAO MG24, debug Thread attachment
before SRP, CoAP, or rig discovery. A missing child means the device has not
joined the Thread mesh yet.

Build the UART/shell SED functional test image without changing the production
build output:

```bash
just power-si::mcu::build-sed-debug
```

The SED debug HEX is:

```text
devices/power-si/mcu/build/zephyr-xiao_mg24-sed-debug/zephyr/zephyr.hex
```

The `sed-debug` profile enables the UART shell and OpenThread logs, and applies
the isolated RadioAES CCM candidate for this one build. It keeps
`IEEE802154_HW_TX_SEC` enabled and uses RadioAES ECB only to create the tag for
an empty encrypted CCM message. The candidate contains no logging, does not
rewrite emitted frames, and does not change radio TX power. It additionally
enables the debug-only SED recovery experiment. After the post-SRP transition,
it retries a persistent lost attachment in the requested link posture: REDCON
4 retries as SED, while the test-only receiver-on REDCON 3 posture retries as
receiver-on MTD.

If a candidate build is interrupted before cleanup and the Silabs HAL checkout
is left dirty, reverse the patch before running normal stock builds:

```bash
git -C devices/common/mcu/zephyr/modules/hal/silabs apply --reverse \
  ../../../../patches/silabs-radioaes-zero-length-ccm.patch
```

To test that image on hardware, flash the SED debug build through the device-owned
flash target. The flash recipe uses the already-built HEX and does not rebuild,
so rerun `just power-si::mcu::build-sed-debug` after every firmware source change
before flashing:

```bash
just power-si::mcu::flash sed-debug
```

Open the XIAO MG24 USB CDC serial port at 115200 baud:

```bash
just power-si::mcu::log
just power-si::mcu::log <serial-port>
```

Keep the log open while resetting the board. If the board already booted before
the serial session opened, press Enter to show the Zephyr shell prompt.

Expected boot evidence:

```text
txing power-si boot
loaded TXT1 factory data for <thing-name>
Thread active dataset accepted: <n> TLV bytes
Thread SRP bootstrap mode configured: rxOnWhenIdle=1 poll=5000 ms fullNetworkData=1
Thread IPv6 interface enabled
Thread protocol enabled
Thread state flags=... role=child
SRP update accepted
Thread SED link mode configured after SRP registration: rxOnWhenIdle=0 poll=5000 ms fullNetworkData=1
Thread switched to SED mode after SRP registration
```

If `loaded TXT1 factory data` is missing, debug factory programming or the flash
partition before looking at radio behavior. If the dataset is accepted but the
role stays `detached`, compare the active dataset with the OTBR and inspect
radio/network state. If the device reaches `child` in the bootstrap posture but
never logs `SRP update accepted`, debug SRP server discovery, reachability, and
client state before looking at rig discovery.

Ordinary `debug` uses the normal receiver-on fallback once per boot to keep
SRP/CoAP usable when a SED attachment fails:

```text
Thread SED mode did not remain attached: role=detached rxOnWhenIdle=0; reverting to SRP bootstrap mode
Thread SRP bootstrap mode configured: rxOnWhenIdle=1 poll=5000 ms fullNetworkData=1
Thread restarted in SRP bootstrap mode after SED fallback
```

That fallback is diagnostic only. It is a hardware/software blocker signal to
record with the log excerpt, OTBR child table, and SRP service output.

The final release and `sed-debug` intentionally do not use that fallback. After
the post-SRP SED transition, both attempt recovery in the requested link
posture at most three times, with 5, 10, and 20 second delays. A normal
transient detach can reattach before a recovery attempt; `sed-debug` logs the
attempts for diagnosis:

```text
Thread requested link mode lost: role=detached rxOnWhenIdle=0 requested=n; scheduling recovery 1/3 in 5 s
Thread attempting requested link-mode recovery 1/3: role=detached rxOnWhenIdle=0 requested=n
Thread restarted in SED mode during SED recovery
```

When REDCON is 3, the corresponding requested value is `rn`; when REDCON is 4,
it is `n`. If all three attempts fail, the image logs that requested-link
recovery is exhausted; save that log and the OTBR evidence rather than treating
it as a successful recovery.

Useful Zephyr shell checks on the XIAO MG24:

```text
ot state
ot mode
ot pollperiod
ot dataset active -x
ot ipaddr
ot srp client state
ot srp client host
ot srp client service
```

Do not paste or commit the dataset TLV output. It is only for local comparison
with the OTBR dataset.

Useful OTBR checks:

```bash
sudo ot-ctl state
sudo ot-ctl dataset active -x
sudo ot-ctl child table
sudo ot-ctl neighbor table
sudo ot-ctl srp server host
sudo ot-ctl srp server service
```

For the SED contract, the XIAO MG24 shell should report `ot mode` as `n` and
`ot pollperiod` as `5000`. On the OTBR, the `child table` row for the device
should show the receiver-on flag as false (`R=0`) while the SRP service remains
registered.

Minimal TASK-21.5 SED evidence to capture from the debug image:

```text
uart:~$ ot state
child
Done
uart:~$ ot mode
n
Done
uart:~$ ot pollperiod
5000
Done
```

```bash
sudo ot-ctl child table
sudo ot-ctl srp server service
```

The `child table` row for the XIAO MG24 extended MAC must show `R=0`, and the
`power-si._txing-coap._udp.default.service.arpa.` service must show
`deleted: false`, port `5683`, and TXT values for `type=power-si` and `pv=1`.

`sed-debug` temporarily applies one isolated downstream HAL candidate while
building, then reverses it before the build exits. It changes only the Silabs
RadioAES CCM encryption implementation in `hal_silabs`: an empty message with a
MIC derives its CCM tag from B0 and formatted AAD with the existing RadioAES ECB
primitive instead of using the empty-payload CCM DMA descriptor. The candidate
has no logging and neither rewrites a MIC, alters retries, nor disables hardware
TX security. Normal `build` and `build-debug` images use unmodified stock
sources.

Use the candidate image to copy the device address from the SRP service output,
reset the parent MAC counters, and send traffic from the OTBR to the sleeping
child. The `10` second ping timeout covers two 5000 ms poll periods:

Before flashing, unregister the service from the currently running debug image
so an old SRP lease cannot produce a false positive. First use `ot srp client
service` on the device to read its exact instance and service names, then set
the instance variable and run:

```bash
SERVICE_INSTANCE='power-si'
ot srp client service remove "$SERVICE_INSTANCE" _txing-coap._udp
```

Confirm `sudo ot-ctl srp server service` reports that service as
`deleted: true`, then flash and reset the test `sed-debug` image. Its
subsequent `deleted: false` entry is fresh registration evidence.

After the device registers again, run the indirect-delivery test:

```bash
DEVICE_ADDRESS='fd00:0000:0000:0000:0000:0000:0000:0001'
# Replace the example above with the address in `addresses: [...]` for this service.
sudo ot-ctl counters mac reset
sudo ot-ctl ping "$DEVICE_ADDRESS" 8 3 1 64 10
sudo ot-ctl counters mac
sudo ot-ctl child table
sudo ot-ctl srp server service
```

Do not paste an angle-bracket placeholder into a shell command: Bash interprets
`<...>` as input redirection and sends no ping.

The ping must receive replies, proving that the parent queued an indirect
request and the child received and answered it. The parent counters must show
`RxDataPoll` increasing and `RxErrSec: 0`. After at least one minute, re-run the
device `ot state` and `ot mode` commands and the OTBR child/SRP checks. The
device must remain `child` in mode `n`, the parent row must remain `R=0`, and
the SRP service must remain `deleted: false`. An unexpected switch to requested
mode `rn`, a SED-recovery exhaustion log in `sed-debug`, a missing child, an
increasing `RxErrSec`, or failed indirect pings means this candidate does not
fix the SED path. The OTBR counters and indirect-delivery result are the
acceptance signal. A successful run remains a downstream candidate until the
owning upstream accepts an equivalent fix.

## Release Current and Battery Measurement

Use current measurement only after the final release image proves the device can
attach, register SRP, and settle as `ot mode=n`. Build the release image if the
firmware, Zephyr workspace, or candidate patch changes:

```bash
just power-si::mcu::build
```

Flash the already-built candidate image manually:

```bash
just power-si::mcu::flash
```

The final release loads `sed-debug.conf` before its silent release overlay, so
it shares the same receiver-on SRP bootstrap, SED recovery, REDCON 3/4
link-mode policy, and RadioAES candidate as `sed-debug`. It keeps the serial
driver baseline but does not enable a console, shell, UART logging, OpenThread
diagnostics, or PM transition logging. Its additional functional path is
on-demand battery sampling. PD3 is inactive between requests; a CoAP state or
REDCON response briefly enables PD3, waits 30 ms for the divider to settle,
samples PD4 using the calibrated 1.21 V internal IADC reference at 0.5x gain,
converts the result to millivolts, and applies the board's 2:1 divider ratio.
This does not establish a causal claim about current consumption. Use OTBR state
to distinguish idle SED polling from active queued traffic:

```bash
sudo ot-ctl child table
sudo ot-ctl srp server service
```

The child table must show the device with `R=0`, and SRP must remain
`deleted:false` on port `5683`. Power the board only from the measurement setup
with USB disconnected. Set the meter to DC-current mode before connecting it in
series with the battery. Measure after SRP registration completes and the child
settles into SED polling. Do not use a run with `R=1` as an SED current baseline
because REDCON 3 intentionally requests receiver-on mode in this test profile.

Record the meter range, DC-current setting, supply voltage, sampling/averaging
mode, parent `QMsgCnt`, and whether traffic is being sent. For an idle baseline,
wait for `QMsgCnt=0` and one subsequent 5000 ms poll. Then repeat the
measurement while known indirect traffic is queued. Do not assign a current
floor or a causal explanation until the DC readings have been recorded under
both conditions.

For battery validation, request `GET /txing/v1/state` with the same CoAP test
client used for protocol acceptance. The response must contain an integer near
the independently measured battery voltage rather than `null`, for example:

```json
{"version":1,"thingName":"power-si-example","redcon":4,"batteryMv":3980}
```

Repeat the request after REDCON 3 and REDCON 4 commands because their response
payloads use the same sample path. With `txing-thread-connectivity` running,
confirm that the non-null value reaches the named `power` shadow. A missing ADC
sample deliberately remains `batteryMv: null`; it must not publish a fabricated
zero-voltage reading.

## Hardware Acceptance

Record manual acceptance in the Backlog task or linked lab notes without
including dataset TLVs. A complete `power-si` hardware acceptance record should
include:

```text
Date:
Operator:
Thing name:
Hardware:
Firmware git SHA:
Rig release/version:
OTBR/network source label, without dataset TLVs:
Factory HEX generated: pass/fail, command output summary:
Firmware flashed manually: pass/fail, command output summary:
Factory HEX flashed manually: pass/fail, command output summary:
SRP service: _txing-coap._udp.default.service.arpa, instance, AAAA, TXT, port:
SED evidence: ot mode=n, ot pollperiod=5000, OTBR child table R=0:
SED debug profile flashed: pass/fail, command output summary:
SED sleep-current measurement:
Rig discovery log excerpt:
REDCON 4 command result:
REDCON 3 command result:
D1 output measurement at REDCON 4:
D1 output measurement at REDCON 3:
Board LED follows power state:
Battery millivolt shadow update:
Sparkplug DBIRTH/DDATA/DDEATH evidence:
Unexpected behavior:
```

Acceptance is complete only when the evidence covers user-run factory
provisioning, user-run firmware/factory flashing, SRP registration, rig
discovery, REDCON 4/3 transitions, D1 output, battery shadow updates, and
Sparkplug birth/data/death behavior.
