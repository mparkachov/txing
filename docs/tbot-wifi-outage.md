# TBot Wi-Fi outage diagnosis and bounded mitigation

## Operator disposition — closed on 2026-10-25

The operator continued observing TBot for another hour or so after the
recorded trial, then confirmed that it lost battery power and transitioned
to actual REDCON 4. One battery supplies both the MCU and Pi. The battery
hardware issue will be handled in another system, outside #171; the operator
explicitly requested closure of this repository investigation. No destination
system or external tracking reference was specified.

This later event is operator-confirmed. It occurred after the automated
captures ended; an exact event time, new kernel trace and electrical
measurements were not supplied. The earlier DMA Oops and bounded 25 MHz
observation below remain historical evidence. A kernel repair was not
implemented or verified by this investigation.

The last verified boot configuration retains the operator-applied 25 MHz
SDIO setting with root and boot read-only. Closing the issue performs no
device deployment or restoration. The procedures below are retained as
diagnostic reference; battery hardware diagnosis and repair are handled in
the other system.

## Captured failure

The captured #171 incident is a Linux fault in the onboard Wi-Fi SDIO DMA
path. On 2026-10-22 the Raspberry Pi Zero 2 W running Alpine 3.24.1,
`linux-rpi 6.18.44-r0`, faulted in `bcm2835_mmc_transfer_dma+0x88/0x248`
on `brcmf_sdio_dataworker`. Kernel messages show repeated SDIO errors before
the NULL-pointer Oops. KVS continued logging network retries for at least
579 seconds afterward. This establishes broken board networking; it does
not establish that the whole board lost power or stopped executing.

The later unpingable-board symptom during #167 is consistent with this fault,
but that occurrence has no recovered kernel trace. REDCON falling to 3 and
both streams stopping are consequences of losing board availability and do
not independently identify the cause. Power cycling to REDCON 4 discards the
previous boot's RAM logs.

## Current evidence and limits

Initial read-only SSH inspection on 2026-10-25, before the clock trial, confirms:

- Raspberry Pi Zero 2 W Rev 1.0; running and installed kernel 6.18.44.
- `/` and `/boot` read-only; `/var/log`, `/var/tmp` and `/run` on tmpfs.
- Wi-Fi on `mmc1`, driver `mmc-bcm2835`, with DMA allocated and actual bus
  clock 50 MHz. The SD card uses the separate `sdhost-bcm2835` driver.
- BCM43430/2 firmware 9.88.4.77, `linux-firmware-brcm 20260519-r0`,
  `raspberrypi-bootloader 1.20260810-r0`.
- TBot daemon/MAVLink/ArduPilot installation paths at 0.18.12; shared KVS
  master 0.18.2. Resolved paths and binary hashes are retained locally.
- Initial temperature about 58 degrees C, about 278 MiB available memory,
  Wi-Fi signal about -39 dBm and current undervoltage alarm 0. These readings
  do not exclude an intermittent power, thermal or firmware trigger.

A pre-change native observation from 09:31:25 to 09:35:25 UTC received
4,044 telemetry messages and 7,031 video frames in its final sample, with
control false and no observed kernel fault. The observer exited 0 on SIGTERM.
This four-minute smoke baseline does not establish sustained reliability or
validate a mitigation. The boot ID was
`05701fbb-b526-47df-8500-34b52d8ef43e`.

The operator applied the 25 MHz trial and rebooted on 2026-10-25. SSH at
09:43:33 UTC independently confirms actual SDIO clock 25 MHz, unchanged
kernel and binary hashes, read-only root and boot, and new boot ID
`bb5d5309-6c98-4175-b60b-f369100275a1`. DMA remains allocated. A bounded
45-minute budget for concurrent telemetry/video observation with kernel/service
logs, health sampling and planned viewer reconnects started at 09:45:43 UTC.
The diagnostic client was deliberately stopped at 09:54:52 UTC to correct
the harness's initial duration, then resumed at 09:55:37 UTC with the remaining
budget and the same absolute end at 10:30:43 UTC. The approximately 45-second
media-observation gap is retained; it was not a board restart or failure.
The bounded observation completed at 10:30:43 UTC without a recorded kernel
fault, unexpected reboot or SSH loss. This is finite trial evidence; the
initiating hardware/firmware/timing trigger remains unresolved.

### Recorded 25 MHz observation

- Main native clients received 45,692 telemetry messages and 79,146 H.264
  frames in their final sampled counters across the two phases. They held no
  authority and sent no uplink datagrams. The planned restart gap above is
  retained; no continuous 45-minute media receipt is claimed.
- An extra viewer received 966 telemetry messages / 1,648 frames, closed,
  then reopened and received 934 messages / 1,619 frames. Both viewer
  processes exited 0 on the planned close while the main streams continued.
- All 264 health samples retained the same boot ID and actual 25 MHz clock.
  Recorded root/boot mounts remained read-only and the four service PIDs
  remained unchanged. The sampled Pi undervoltage alarm was always 0.
- Temperature ranged from 63.376 to 69.294 degrees C and available memory
  from 263.3 to 273.3 MiB. The main clients recorded 169 bounded consumer
  queue drops across the two phases; this is not an RTP packet-loss metric.
- No equivalent 45-minute 50 MHz baseline was recorded. The earlier
  four-minute baseline also had no fault, so this observation does not
  establish causality or a permanent repair. Board credential renewal and
  QGroundControl parameter-write/control workload were not validated.

Audited evidence is `tmp/issue-171/25mhz-validation-audit.json` with raw kernel,
health, service and native logs in `25mhz-trial-01/` and `25mhz-trial-02/`.
The active setting remains the operator-applied 25 MHz clock; no kernel,
package, firmware, worker, protocol or service repair has been deployed.

The exact Alpine 6.18.44 and 6.18.58 driver files previously captured, and a
fresh GitHub API read of the Raspberry Pi `rpi-6.18.y` driver on 2026-10-25,
are identical: SHA-256
`d2bbd5afc2faa31b8839aa8071d2464aa4361c9ae86824ab0f7f43e2851a5ef6`.
An upgrade has not been established as a repair for this driver fault.

Source review identifies a plausible synchronization defect: request setup
releases `host->lock` after sending the hardware command, then enters DMA
setup. DMA setup checks `host->data` but rereads it without holding that lock;
completion can clear the pointer. The saved fault instruction is
`ldr x1, [x0, #56]`, with `x0=0`, immediately after loading a pointer from
`[x19, #240]`. The offset 56 matches `struct mmc_data.sg` on AArch64. This
strengthens the NULL data-pointer explanation. A matching deployed
`vmlinux`/full disassembly, the initiating SDIO failure and a tested driver
repair remain outstanding. Adding another NULL check or saving a pointer
alone would not establish correct request lifetime.

Raw evidence stays in ignored workspace scratch directories:
`tmp/issue-165/board-after-sixth-kernel-oops.log`, the original recovered
archive referenced by #171, and `tmp/issue-171/`. Do not publish unreviewed
service logs, credentials, SDP or signed URLs.

### Battery and power evidence

The operator observed a yellow Office battery indicator during the 25 MHz
trial and confirmed that one battery supplies both the MCU and Pi. The
converter/regulator topology is not established. The first captured
power-shadow value was 3,730 mV, last changed at
10:01:02 UTC on 2026-10-25. Office's TBot panel maps that to an estimated 26%
and yellow; its yellow range is 20% up to 55%. This is a voltage-derived
display estimate, not a Pi supply-voltage measurement.

An initial snapshot at 10:10:05 UTC and 237 shadow read cycles from
10:13:01 to 10:32:45 UTC all returned that same value and the same original
field timestamp, with no power/lifecycle read failures and reported REDCON 1.
Battery capture began partway through the native trial and continued for two
minutes after its end. These are retained-shadow observations, not 237 fresh
ADC measurements. The earlier October 21 outage artifact reports 4,135 mV,
but that field was already almost 16 hours old when read; it does not rule out
a power problem at that outage or establish battery condition at the later
October 22 kernel crash.

The rig publishes a Thread battery shadow only for the first valid value or
a later change **greater than 10%** from the last published baseline.
Repeated shadow reads therefore do not measure small dips or establish a
steady live battery voltage. Retain both the observation time and the battery
field's own metadata timestamp. Fresh MCU state queries and Pi rail/undervoltage
evidence are separate observations. Sampled Pi undervoltage alarm 0 does not
exclude short or unobserved dips, regulator trouble or a Wi-Fi supply issue.
The captured DMA Oops establishes a kernel fault; it does not rule out a power
or other hardware trigger for the preceding SDIO errors.
Battery observations in this record use shadows only, per the operator's
instruction; rig SSH was not used.

## Capture while the board stays read-only

Normal Office recovery is REDCON 4, confirm board power off, then REDCON 1.
Leave TBot disarmed with tracks lifted or motor power isolated. The rig and
MCU remain powered. No serial connection is required for these SSH checks.

On the Mac, in the repository root:

```sh
mkdir -p tmp/issue-171
ssh -o BatchMode=yes -o ConnectTimeout=5 \
  -o ServerAliveInterval=5 -o ServerAliveCountMax=2 root@192.168.0.10 '
  date -u
  uname -r
  cat /proc/sys/kernel/random/boot_id
  cat /proc/uptime
  awk '\''$2 == "/" || $2 == "/boot" || $2 == "/var/log" { print }'\'' /proc/mounts
  cat /sys/kernel/debug/mmc1/ios
  dmesg
' > tmp/issue-171/baseline-current.txt
```

Keep the following running in a second Mac terminal during a bounded test.
Choose a new output filename for each boot/trial to preserve earlier evidence:

```sh
ssh -o BatchMode=yes -o ConnectTimeout=5 \
  -o ServerAliveInterval=5 -o ServerAliveCountMax=2 root@192.168.0.10 \
  'timeout 2700 cat /dev/kmsg' \
  > tmp/issue-171/kernel-trial.log \
  2> tmp/issue-171/kernel-trial.stderr
```

The deployed BusyBox `dmesg` has no follow option. Reading `/dev/kmsg` uses a
reader-specific cursor and does not clear the kernel ring. Capture service
logs separately with a bounded `tail -F` if needed. Keep boot ID, UTC and
uptime with samples; wall-clock timestamps alone can jump during NTP startup.

Network-only capture can lose the final crash trace when the failing path is
Wi-Fi itself. No read-only, RAM-only logging method can retain new evidence
through complete removal of board power. A later final-trace capture would
require a separately reviewed persistent logging window, accessible external
storage or an independent transport. The existing
[persistent capture procedure](tbot-outage-capture.md) deliberately requires a
writable root and is not the read-only procedure above.

## First trial: documented 25 MHz Wi-Fi bus setting

Start with this bounded mitigation because it uses an existing firmware
parameter, changes one variable and needs no package or kernel replacement.
It may reduce SDIO timing errors or the conditions that expose the race; it
does not remove DMA or repair the synchronization defect. Throughput may fall.
Keep all software versions and other Wi-Fi settings fixed during the trial.

This is an **operator-run maintenance step**, as required for changes to a
board already in service by the
[repository deployment boundaries](agent-guidance/editing-boundaries.md).
Root stays read-only. Only `/boot` is briefly writable. Do not use `root-rw`
or `root-ro`: those aliases also alter live tmpfs state.

On the board in the operator's privileged SSH session, run this complete
block once. It refuses to overwrite a prior backup or an existing clock
override. Inspect a refusal rather than bypassing it:

```sh
(
  set -eu
  grep -qxF 'include usercfg.txt' /boot/config.txt
  test -r /sys/kernel/debug/mmc1/ios
  cat /sys/kernel/debug/mmc1/ios
  test ! -e /boot/usercfg.txt.before-issue-171
  if grep -Eq '^[[:space:]]*dtparam=.*sdio_overclock[[:space:]]*=' /boot/usercfg.txt; then
    echo 'An SDIO clock override already exists; inspect it first.' >&2
    exit 1
  fi
  mount -o remount,rw /boot
  trap 'sync; mount -o remount,ro /boot' 0
  cp /boot/usercfg.txt /boot/usercfg.txt.before-issue-171
  printf '\n[all]\n# issue-171-sdio-clock-trial\ndtparam=sdio_overclock=25\n' >> /boot/usercfg.txt
  sync
  mount -o remount,ro /boot
  trap - 0
  cat /boot/usercfg.txt
  awk '$2 == "/" || $2 == "/boot" { print }' /proc/mounts
)
```

If writing or remounting fails, preserve the output and inspect the file and
mount state before restarting. After a successful read-only remount, reboot
manually through Office REDCON 4 then 1. Reconnect and run:

```sh
date -u
uname -r
cat /proc/sys/kernel/random/boot_id
cat /sys/kernel/debug/mmc1/ios
awk '$2 == "/" || $2 == "/boot" || $2 == "/var/log" { print }' /proc/mounts
dmesg | grep -E 'mmc-bcm2835|DMA channel|brcmfmac'
```

Require a new boot ID, unchanged kernel, root and boot read-only, and
**actual clock** approximately 25 MHz. The requested clock can still display
50 MHz. A line in `usercfg.txt` without an actual-clock change is not an
active trial. DMA remains enabled in this trial.

### Validation and restoration

Run concurrent real telemetry and video with the kernel capture already
active. Use an observation-only native client and leave authority unowned.
Record received counters, a UTC start/end window, boot ID, reachability,
temperature, memory, SDIO errors and packet loss. Include normal viewer
disconnect/reconnect activity; do not change service ownership or automatic
recovery behavior to hide a failure.

A 45-minute first window exercises the observed short-failure workload while
remaining within the existing
[50-minute agent-session limit](constraints/agent-session-limit.md). It is a
bounded acceptance observation, not proof of indefinite reliability. It does
not validate the deferred board credential-renewal path. A fresh agent process
does not reset board credential age, so renewal can interrupt an older board
earlier; classify that separately using kernel logs, boot ID and reachability.
Longer agent sessions need a separate explicit decision under that constraint.
Repeat representative testing afterward within the same operational limit.
Fail the trial for another MMC warning/Oops, networking loss, reboot, stopped
telemetry/video without recovery, or unacceptable throughput/CPU behavior.
REDCON 1 or successful ping alone does not prove received media is advancing.
A short smoke test or the clock setting alone does not establish a permanent
repair. The operator-directed battery hardware disposition above is the basis
for closing #171.

To restore, save trial evidence first. In a manual writable-boot window,
remove only `# issue-171-sdio-clock-trial` and its adjacent
`dtparam=sdio_overclock=25` line. Remove the added `[all]` only if it remains
unused and has no later settings beneath it. Keep unrelated changes. The
backup is a reference; do not overwrite subsequent edits blindly. Sync,
remount `/boot` read-only, reboot normally, and verify actual clock returns
to 50 MHz. If SSH cannot return, make this same edit on the boot partition
with a card reader; serial access is unnecessary for restoration.

## Unselected reference: Wi-Fi PIO

This candidate was not selected or deployed for #171. Battery hardware
follow-up is handled in another system under the disposition above.

An alternative bypasses the faulting DMA routine by changing only the Wi-Fi
host's `dma-names` property to an unused name. The exact deployed driver tries
`rx-tx`, `tx`, then `rx`; if none resolve, it sets `have_dma=false` and logs
`Unable to initialise DMA channel. Falling back to PIO`. The SD card uses a
different host and need not lose DMA. `sd_force_pio` targets that SD-card host
and is not the Wi-Fi workaround.

The diagnostic source and compiled artifact are prepared locally at
`tmp/issue-171/txing-wifi-pio.dts` and `txing-wifi-pio.dtbo`. Applying the
overlay offline to the actual board's captured FDT succeeds and changes only
`/soc/mmcnr@7e300000/dma-names`, from `rx-tx` to `unused`. It does not alter
Wi-Fi pins, SD-card configuration, PWM or the camera. This checks overlay
targeting, not booting or runtime stability.

PIO has CPU and interrupt-latency costs on the stock kernel, especially during
concurrent video. A recent Zero 2 W project uses the same mechanism along
with a threaded-IRQ kernel patch for audio latency; that is independent
evidence of feasibility, not validation on Alpine/TBot. No custom kernel,
foreign service configuration or PIO overlay has been installed on TBot.
Review this alternative separately if the first trial fails; do not combine
it with the clock change during initial diagnosis.

## Primary references

- [Driver at the inspected upstream revision](https://github.com/raspberrypi/linux/blob/aeadd6ed6be07f1350627dcd0fb14393f5abde56/drivers/mmc/host/bcm2835-mmc.c).
- [Raspberry Pi parameter reference](https://github.com/raspberrypi/linux/blob/rpi-6.18.y/arch/arm/boot/dts/overlays/README)
  and [parameter-to-host mapping](https://github.com/raspberrypi/linux/blob/rpi-6.18.y/arch/arm/boot/dts/broadcom/bcm270x-rpi.dtsi).
- [Related Zero 2 W Wi-Fi issue](https://github.com/raspberrypi/linux/issues/5770);
  similar errors do not prove an identical initiating defect.
- [Independent Wi-Fi PIO mitigation](https://github.com/nexxyz/octessera/commit/b187ef6a64962f9fc5be2d54739be3eba379e373).
- [Issue #171](https://github.com/mparkachov/txing/issues/171).
