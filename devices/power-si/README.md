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

Real Thread dataset TLVs are credentials. Do not commit them, paste them into
Backlog tasks, or store them under version control. Use a local ignored path
such as `tmp/power-si-dataset.hex` or another operator-controlled secret
location. Recording a short non-secret source label, timestamp, or OTBR/network
name in acceptance notes is fine; recording the TLVs is not.

Prepare the shared stock Zephyr workspace once:

```bash
just mcu::install
just mcu::check
```

Validate and generate the factory HEX:

```bash
python3 devices/common/mcu/xiao_mg24/scripts/thread_factory.py validate \
  power-si-001 \
  --dataset-tlvs tmp/power-si-dataset.hex

just power-si::mcu::factory-hex \
  power-si-001 \
  tmp/power-si-dataset.hex
```

The default output is:

```text
devices/common/mcu/build/power-si-thread-factory.hex
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

## Manual Flashing

Agents must not flash hardware. The operator flashes both artifacts manually
using the debugger and runner available for the XIAO MG24 setup.

After `just power-si::mcu::build`, inspect the Zephyr runner context for the
connected board:

```bash
devices/common/mcu/.venv/bin/west \
  -z devices/common/mcu/zephyr/zephyr \
  flash \
  --context \
  -d devices/power-si/mcu/build/zephyr-xiao_mg24
```

Then flash firmware with the appropriate runner. For a J-Link setup, the command
shape is:

```bash
devices/common/mcu/.venv/bin/west \
  -z devices/common/mcu/zephyr/zephyr \
  flash \
  -d devices/power-si/mcu/build/zephyr-xiao_mg24 \
  -r jlink \
  --no-rebuild
```

Program the factory HEX with the same connected-debugger tooling. Confirm the
runner supports an external HEX override before running it:

```bash
devices/common/mcu/.venv/bin/west \
  -z devices/common/mcu/zephyr/zephyr \
  flash \
  --context \
  -d devices/power-si/mcu/build/zephyr-xiao_mg24 \
  -r jlink

devices/common/mcu/.venv/bin/west \
  -z devices/common/mcu/zephyr/zephyr \
  flash \
  -d devices/power-si/mcu/build/zephyr-xiao_mg24 \
  -r jlink \
  --no-rebuild \
  --hex-file devices/common/mcu/build/power-si-thread-factory.hex
```

If the selected runner does not support `--hex-file`, use the matching vendor
programmer to write
`devices/common/mcu/build/power-si-thread-factory.hex` without erasing the
firmware image.

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
