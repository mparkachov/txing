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

## Rig Prerequisites

`power-si` requires a `raspi` rig running the three rig daemons documented in
[Rig](../../docs/components/rig.md):

- `txing-sparkplug-manager`
- `txing-thread-connectivity`
- `txing-ble-connectivity`

The Thread daemon does not install or configure OTBR. Before provisioning a
device, the operator must have an external OTBR already joined to the target
Thread network and reachable from the rig network. The default discovery domain
is `default.service.arpa`; override it with `TXING_THREAD_SERVICE_DOMAIN` only
when the OTBR network uses a different SRP/DNS-SD domain.

Run these checks from the rig or from a machine on the same IPv6 network before
expecting `txing-thread-connectivity` to discover a device:

```bash
systemctl status --no-pager -l txing-thread-connectivity.service
journalctl -u txing-thread-connectivity.service -n 160 --no-pager
avahi-browse -rt -d default.service.arpa _txing-coap._udp
```

`avahi-browse` may return no services before a provisioned `power-si` has
joined and registered SRP. That is acceptable; DNS-SD lookup failures in the
Thread daemon should be bounded log events, not service crashes.

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

Normal release and debug builds use stock Zephyr sources. Current XIAO MG24 SED
hardware evidence shows stock Zephyr/Silabs hardware MAC TX security breaks
secured sleepy MAC Data Request frames: the OTBR rejects polls before data-poll
handling, so the device cannot stay attached as an SED. Use the explicit SED
test profiles below while the upstream issue is open. They apply only the
minimal local Zephyr workaround needed for hardware validation: enable
OpenThread software MAC TX security for Silabs S2 and stop advertising the
Silabs `IEEE802154_HW_TX_SEC` capability. The build script applies the patch
before the build and reverses it immediately afterward so the local Zephyr
checkout returns to stock.

Build a serial/shell functional SED test image:

```bash
just power-si::mcu::build-sed-debug
```

The expected debug SED test HEX is:

```text
devices/power-si/mcu/build/zephyr-xiao_mg24-sed-debug/zephyr/zephyr.hex
```

Build a silent SED current-measurement image:

```bash
just power-si::mcu::build-sed-current
```

The expected current-measurement HEX is:

```text
devices/power-si/mcu/build/zephyr-xiao_mg24-sed-current/zephyr/zephyr.hex
```

The current-measurement profile keeps the same SED workaround and application
behavior as `sed-debug`, but adds Zephyr PM (`CONFIG_PM=y`) and disables UART,
console, printk, boot banner, and logging. Use `sed-debug` first to prove
Thread/SRP/CoAP behavior, then flash `sed-current` for sleep-current
measurement. A silent serial port is expected for `sed-current`.

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
just power-si::mcu::flash sed-current
```

The flash recipe does not rebuild. Re-run the matching `build*` command after
source or configuration changes before flashing a profile.

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
the minimal Silabs SED workaround for this one build. It does not change radio
TX power.

If a SED test build is interrupted before cleanup and the Zephyr checkout is
left dirty, reverse the test patch before running normal stock builds:

```bash
git -C devices/common/mcu/zephyr/zephyr apply --reverse \
  ../../patches/silabs-efr32-sed-data-poll-rx-test.patch
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

If the current Zephyr/Silabs SED path cannot keep the device attached, the debug
log can show the SED transition followed by `role=detached` and data poll
timeouts. After a short guard window, the firmware then restarts Thread in
receiver-on SRP bootstrap mode once per boot to keep SRP/CoAP usable:

```text
Thread SED mode did not remain attached: role=detached rxOnWhenIdle=0; reverting to SRP bootstrap mode
Thread SRP bootstrap mode configured: rxOnWhenIdle=1 poll=5000 ms fullNetworkData=1
Thread restarted in SRP bootstrap mode after SED fallback
```

That fallback is not TASK-21.5 acceptance evidence. It is a hardware/software
blocker signal to record with the log excerpt, OTBR child table, and SRP service
output.

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

## SED Current Measurement

Use current measurement only after the `sed-debug` image proves the device can
attach, register SRP, and settle as `ot mode=n`. Build the silent PM-enabled
image:

```bash
just power-si::mcu::build-sed-current
```

Flash the already-built current image manually:

```bash
just power-si::mcu::flash sed-current
```

The `sed-current` image has UART, shell, printk, boot banner, and logging
disabled, and enables Zephyr PM so the SoC can sleep between the 5000 ms Thread
polls. Do not use the USB serial log as the validation signal for this image; a
silent port is expected. Validate from OTBR and rig-side evidence:

```bash
sudo ot-ctl child table
sudo ot-ctl srp server service
```

The child table must show the device with `R=0`, and SRP must remain
`deleted:false` on port `5683`. For current measurement, power the board from
the measurement setup rather than relying on USB-powered serial debugging, and
measure after the SRP registration has completed and the child has settled into
the steady SED polling state.

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
SED current profile flashed: pass/fail, command output summary:
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
