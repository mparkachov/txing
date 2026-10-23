# Capture a TBot board outage across a restart

Use this manual procedure for `tbot-8yzfgj` before retrying #165. It captures
kernel/system messages, existing service stdout/stderr, installed versions and
periodic machine state. The board's normal `/var/log` and `/var/tmp` are tmpfs;
those logs disappear when board power is removed.

For this diagnostic session, keep the ext4 root writable and bind a directory
under `/root/tbot-capture/` over `/var/log`. Existing OpenRC services then write
their usual log paths to storage. The bind mount is temporary: after reboot,
normal tmpfs logging returns, while the old capture remains under `/root`.
No fstab change, new service, firmware update or runtime upgrade is required.
Keep the tracks lifted or motor power isolated and leave the rover disarmed.

## 1. Wake the board and obtain SSH access

If the board is currently unreachable, use the normal Office flow: request
REDCON 4, wait for confirmation that board power is off, then request REDCON 1.
This first recovery power cycle cannot preserve the previous boot's RAM logs.
Keep the rig and TBot MCU powered and reachable. Actual REDCON can remain 3
while Linux boots and its services become ready.

On the **Mac**, in the repository root:

```sh
export BOARD_HOST=192.168.0.10
date -u
ssh -o ConnectTimeout=5 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
  root@"$BOARD_HOST"
```

`192.168.0.10` was the last reported board address. Check the router's current
DHCP lease for `tbot` and replace it if it changed. Use the existing SSH key;
do not disable host-key verification. If it still cannot connect after a normal
boot, check wired access if available or obtain a local/serial console. Remount
and logging commands cannot be run remotely until Linux is reachable. Do not
reflash the card to recover access: it contains the evidence and configuration.

## 2. Check the clock, network and persistent root

Run on the **board as root**. Compare UTC with the Mac, including date and year:

```sh
date -u
uptime
cat /etc/alpine-release
cat /proc/sys/kernel/random/boot_id
awk '$2 == "/" || $2 == "/var/log" || $2 == "/var/tmp" { print }' /proc/mounts
df -h / /var/log /var/tmp
ip address show
ip route show
readlink /etc/resolv.conf
getent hosts a28845zlj97ljp-ats.iot.eu-central-1.amazonaws.com
rc-service ntpd status
```

The root must be the persistent ext4 sys install, not a diskless tmpfs root.
Keep `/tmp`, `/var/tmp` and `/run` mounted. A started `ntpd` process alone does
not establish correct time. If UTC is wrong, stop the TBot stack in reverse
order as listed in step 3, then synchronize using the existing NTP client:

```sh
rc-service ntpd stop
ntp_result=0
timeout 60 ntpd -n -q -p pool.ntp.org || ntp_result=$?
rc-service ntpd start
printf 'one-shot NTP result: %s\n' "$ntp_result"
date -u
```

Use the deployment's reachable NTP server instead if public NTP is blocked.
Do not start AWS-backed workers until UTC is correct. This is a manual
diagnostic step with the existing client, not a clock-ready service.

## 3. Remount only root and prepare persistent logging

Run each parenthesized block as a unit; it stops at an unexpected failure.
The `root-rw`/`root-ro` aliases are unsuitable here: the documented aliases
unmount or clear `/tmp` and `/var/tmp`, which contain live runtime state.
There is no need to remount `/boot` or change `/etc/fstab` for this capture.
Run setup once per boot. If `/var/log` is already bound to a capture directory,
reuse that capture rather than stacking another bind mount over it.

On the **board**:

```sh
(
  set -eu
  test "$(awk '$2 == "/" { print $3; exit }' /proc/mounts)" = ext4
  test "$(awk '$2 == "/var/log" { type=$3 } END { print type }' /proc/mounts)" = tmpfs
  mount -o remount,rw /
  umask 077
  capture_id="$(date -u +%Y%m%dT%H%M%SZ)-$(cut -c 1-8 /proc/sys/kernel/random/boot_id)"
  capture="/root/tbot-capture/$capture_id"
  test ! -e "$capture"
  mkdir -p "$capture/log" "$capture/before-log"
  available_kb=$(df -Pk "$capture" | awk 'NR == 2 { print $4 }')
  test "$available_kb" -ge 524288
  printf '%s\n' "$capture" > /root/tbot-capture/current-path
  cp -a /var/log/. "$capture/before-log/"
  dmesg > "$capture/kernel-before.log"
  cat /proc/sys/kernel/random/boot_id > "$capture/boot-id"
  date -u > "$capture/started-utc.txt"
  sync
  printf 'capture directory: %s\n' "$capture"
)
```

The free-space check requires at least 512 MiB initially; monitor growth during
the test. If remount fails or reports filesystem errors, retain that output and
stop here. Do not repair a mounted filesystem.

Stop the existing stack so all four services reopen their log files after the
bind mount. Do not run manual copies alongside their supervised processes:

```sh
(
  set -eu
  for service in txing-tbot-kvs-master txing-tbot-daemon txing-tbot-mavlink txing-tbot-ardupilot; do
    rc-service "$service" stop || true
  done
  for binary in txing-board-kvs-master txing-tbot-daemon txing-tbot-mavlink txing-tbot-ardupilot; do
    if pidof "$binary" >/dev/null 2>&1; then
      printf 'still running: %s; stop its existing owner before continuing\n' "$binary" >&2
      exit 1
    fi
  done
  if [ -e /etc/init.d/txing-tbot-hardware-worker ]; then
    capture=$(cat /root/tbot-capture/current-path)
    rc-service txing-tbot-hardware-worker status > "$capture/obsolete-worker-status.txt" 2>&1 || true
    rc-service txing-tbot-hardware-worker stop || true
  fi
  if pidof txing-tbot-hardware-worker >/dev/null 2>&1; then
    echo 'old motor owner is still running; stop its owner before starting ArduPilot' >&2
    exit 1
  fi
  test -x /etc/init.d/syslog
  test -x /etc/init.d/klogd
  rc-service klogd stop || true
  rc-service syslog stop || true
  if pidof syslogd klogd >/dev/null 2>&1; then
    echo 'system logger still running; inspect its owner before continuing' >&2
    exit 1
  fi
  capture=$(cat /root/tbot-capture/current-path)
  cp -a /var/log/. "$capture/log/"
  mount -o bind "$capture/log" /var/log
  df -h "$capture" /var/log
  awk -v path="$capture/log" '$4 == path && $5 == "/var/log" { found=1; print } END { exit !found }' /proc/self/mountinfo
  rc-service syslog start
  rc-service klogd start
  logger -t tbot-capture "persistent-capture-ready $capture"
  sleep 2
  grep -F "persistent-capture-ready $capture" /var/log/messages
  sync
)
```

`/var/log` must now show the same ext4 storage as the capture directory, and
the marker must appear in `/var/log/messages`. If either logger service is
missing or the marker is absent, stop and retain the error plus the installed
`/etc/conf.d/syslog` settings; do not assume kernel logging is working. These
are Alpine's existing syslog/kernel loggers, not a new custom service.

## 4. Record the installation, then start the required processes

On the **board**, save identities and versions before changing any binaries:

```sh
(
  set -eu
  capture=$(cat /root/tbot-capture/current-path)
  {
    date -u
    uname -a
    cat /etc/alpine-release
    cat /proc/mounts
    ip address show
    ip route show
    readlink /etc/resolv.conf
    free -m
    df -h
    rc-update show
    grep -E '^(TXING_THING_ID|AWS_REGION|TXING_DAEMON_CAPABILITIES|TXING_CLOUDWATCH_LOG_GROUP|TXING_CLOUDWATCH_LOG_STREAM)=' \
      /root/.config/txing/tbot-daemon/daemon.env || true
    for tool in txing-tbot-ardupilot txing-tbot-mavlink txing-tbot-daemon txing-board-kvs-master; do
      binary="/root/.local/share/mise/installs/$tool/latest/$tool"
      readlink -f "$binary"
      sha256sum "$binary"
    done
    for tool in txing-tbot-mavlink txing-tbot-daemon txing-board-kvs-master; do
      "/root/.local/share/mise/installs/$tool/latest/$tool" --version
    done
    for service in txing-tbot-ardupilot txing-tbot-mavlink txing-tbot-daemon txing-tbot-kvs-master; do
      sha256sum "/etc/init.d/$service"
    done
  } > "$capture/baseline.txt" 2>&1
  for service in udev udev-trigger udev-settle; do
    rc-service "$service" start
    rc-service "$service" status
  done
  udev_count=$(udevadm info --export-db | grep -c '^P:')
  printf 'udev entries: %s\n' "$udev_count"
  test "$udev_count" -ge 100
  rc-service ntpd status
  rc-service txing-tbot-ardupilot start
  rc-service txing-tbot-mavlink start
  rc-service txing-tbot-daemon start
  rc-service txing-tbot-kvs-master start
  for service in txing-tbot-ardupilot txing-tbot-mavlink txing-tbot-daemon txing-tbot-kvs-master; do
    rc-service "$service" status
  done
  waited=0
  while ! { test -S /run/txing-tbot-mavlink/tbot-mavlink.sock &&
            test -S /run/txing-tbot-daemon/mavlink-bridge.sock &&
            test -S /run/txing-tbot-daemon/board-video-bridge.sock; }; do
    test "$waited" -lt 60 || { echo 'bridge sockets not ready; inspect persisted service logs' >&2; exit 1; }
    sleep 2
    waited=$((waited + 2))
  done
  ss -uanp | grep -F '127.0.0.1:14550'
  if ss -uanp | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\*|::|\[::\]):14550'; then
    echo 'unexpected public MAVLink listener; stop and inspect' >&2
    exit 1
  fi
  : > "$capture/health.log"
  sync
)
```

The startup order is **ArduPilot → MAVLink → daemon → KVS master**. Udev must
have a populated database; the board baseline expects at least 100 entries.
Leave the existing ArduPilot defaults and motor limits intact. This captures
ArduPilot console output; its production DataFlash backend remains disabled.

The existing stdout/stderr paths are:

| Component | Path, now backed by the capture directory |
| --- | --- |
| Kernel, Wi-Fi/DHCP and system messages emitted to syslog | `/var/log/messages` and rotated siblings |
| ArduPilot console | `/var/log/txing-tbot-ardupilot/ardupilot.log` |
| MAVLink service | `/var/log/txing-tbot-mavlink.log` |
| Board daemon | `/var/log/txing-tbot-daemon.log` |
| Camera/KVS master | `/var/log/txing-tbot-kvs-master.log` |

Go daemon and MAVLink files can be quiet between startup/fatal errors; their
emptiness does not establish health or successful CloudWatch delivery. This
procedure captures existing output, not additional internal tracing. Never
dump the complete environment, private key files or credential responses.

## 5. Keep a second copy on the Mac and record machine health

In a **second Mac terminal**, use the current DHCP address and keep it open:

```sh
export BOARD_HOST=192.168.0.10
export TBOT_CAPTURE_DIR="$PWD/tmp/issue-165/board-$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$TBOT_CAPTURE_DIR"
date -u > "$TBOT_CAPTURE_DIR/mac-started-utc.txt"
caffeinate -i ssh -T -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
  root@"$BOARD_HOST" '
    capture=$(cat /root/tbot-capture/current-path)
    exec tail -n +1 -F "$capture/health.log" /var/log/messages \
      /var/log/txing-tbot-ardupilot/ardupilot.log \
      /var/log/txing-tbot-mavlink.log /var/log/txing-tbot-daemon.log \
      /var/log/txing-tbot-kvs-master.log
  ' > "$TBOT_CAPTURE_DIR/board-live.log" 2>&1
```

The command stays in the foreground and prevents idle sleep while it runs.
Keep the Mac powered with its lid open. Its file preserves everything received
even if the board's Wi-Fi or SD card later fails. `tail -F` follows log rotation;
if the installed applet rejects it, retain the error and resolve it before
relying on this second copy. Stop this reader with Ctrl-C after capture.

Back in the **first board terminal**, run this foreground sampler for up to
ninety minutes while doing the retry. It writes a snapshot and flushes disk
every ten seconds; Ctrl-C stops only the sampler:

```sh
(
  capture=$(cat /root/tbot-capture/current-path)
  sample=0
  while [ "$sample" -lt 540 ]; do
    {
      date -u +%Y-%m-%dT%H:%M:%SZ
      cat /proc/sys/kernel/random/boot_id /proc/uptime
      free -m
      df -Pk / /var/log /var/tmp
      ip address show
      ip route show
      cat /proc/net/wireless 2>/dev/null
      for binary in txing-tbot-ardupilot txing-tbot-mavlink txing-tbot-daemon txing-board-kvs-master; do
        printf '%s pids: ' "$binary"
        pidof "$binary" || true
      done
    } >> "$capture/health.log" 2>&1
    sync
    available_kb=$(df -Pk "$capture" | awk 'NR == 2 { print $4 }')
    printf '%s free KiB=%s\n' "$(date -u +%H:%M:%S)" "$available_kb"
    if [ "$available_kb" -lt 262144 ]; then
      echo 'LOW SPACE: end the probe and stop the stack using step 7' >&2
      break
    fi
    sample=$((sample + 1))
    sleep 10
  done
)
```

If this SSH session disconnects, the sampler can stop, but existing OpenRC
services and syslog/kernel logging continue independently. Logs flushed to the
ext4 capture directory survive reboot. An abrupt power loss can still lose
buffered application output and the latest unsynced writes; a hard hang or loss
of power may leave no final error. This is why the Mac copy and boot ID matter.

## 6. Retry the observation with logging already verified

Confirm in Office that actual REDCON is 1 and video is live; leave it active.
Tell Codex **“Board capture is ready; retry #165”**, and include the capture
directory and `baseline.txt`. Keep the sampler and Mac reader running.

The next observation must be a **new** operator-launched MicroVM after review
of the saved outage evidence. Recheck the current accepted image, source hashes,
role, live capabilities and zero active probe runs first. As of 2026-10-22,
`txing-agent-probe-165-c963a8c8a9df` version `1.0` contains the accepted
telemetry-silence recovery correction; `5db8fe4d0334` is the earlier source.
Reuse the corrected role, managed public connectors, no idle policy and the
two-hour cap. No rebuild is needed unless packaged source changes.

All six recorded observers are terminated. The fifth/sixth launch blocks are
historical and must not be reused for another run. The seventh #165 launch is prepared in
`tmp/issue-165/operator-seventh-run.md`, reusing the accepted image without
board changes. Board remediation is separately tracked in #171 outside the
current milestone; the sixth outage capture has been recovered and preserved.
The historical retrieval commands are in
`tmp/issue-165/operator-sixth-outage-retrieve.md`. Cloud launches, auth-token creation and final
termination remain operator-run.

Record the new cloud ID and UTC start time alongside the board capture. Budget
roughly seventy minutes for real credential rotation and successful subsequent
telemetry/video; initial and reopened attachment probes fit in the first
thirty-minute ingress token. No control acquisition or motion is needed.

If connectivity fails, record the exact Mac UTC time and the Office actual
REDCON/target. Preserve logs first if the board is still reachable. If it is
completely unreachable, recover through the normal REDCON 4 → 1 flow only when
ready to retrieve the disk capture. Keep the Mac's partial live log.

The 2026-10-22 sixth-run recovery validated this procedure: the Mac reader
lost contact before the final kernel trace, while the disk archive retained a
NULL-pointer Oops in the Wi-Fi SDIO/MMC DMA workqueue plus several more minutes
of KVS network failures. Preserve both copies; an SSH timeout alone does not
establish that the entire board stopped. The post-recovery boot ID and mount
snapshot confirm the reboot restored read-only root/boot and tmpfs logging.
The incident is recorded in `tmp/issue-165/board-wifi-kernel-oops-report.md`.

## 7. Retrieve evidence after restart and finish the maintenance window

After the board boots again, **retrieve the old capture before creating another
one**. Its pointer remains on persistent root even though `/var/log` is tmpfs
again. No writable-root remount is needed just to read it. On the **Mac**, in
the terminal where `TBOT_CAPTURE_DIR` was set:

```sh
ssh root@"$BOARD_HOST" 'cat /root/tbot-capture/current-path'
ssh root@"$BOARD_HOST" 'date -u; cat /proc/sys/kernel/random/boot_id; uptime' \
  > "$TBOT_CAPTURE_DIR/after-restart.txt"
ssh root@"$BOARD_HOST" '
  capture=$(cat /root/tbot-capture/current-path)
  test -d "$capture"
  tar -C "$capture" -czf - .
' > "$TBOT_CAPTURE_DIR/board-capture.tgz.partial" &&
mv "$TBOT_CAPTURE_DIR/board-capture.tgz.partial" "$TBOT_CAPTURE_DIR/board-capture.tgz"
tar -tzf "$TBOT_CAPTURE_DIR/board-capture.tgz"
```

A changed boot ID proves a reboot; the same boot ID with advancing uptime
suggests lost connectivity without a reboot. Neither alone proves the root
cause. Preserve kernel MMC/I/O, Wi-Fi, OOM and thermal messages; correlate their
times with service PID changes, clock jumps and the cloud log.

If finishing **without a reboot**, first terminate the disposable cloud observer
with its reviewed operator command and stop both foreground readers. Then, on
the **board**, close the writers and restore normal logging/read-only root:

```sh
(
  set -eu
  capture=$(cat /root/tbot-capture/current-path)
  for service in txing-tbot-kvs-master txing-tbot-daemon txing-tbot-mavlink txing-tbot-ardupilot; do
    rc-service "$service" stop
  done
  dmesg > "$capture/kernel-final.log"
  rc-service klogd stop
  rc-service syslog stop
  sync
  umount /var/log
  rc-service syslog start
  rc-service klogd start
  sync
  mount -o remount,ro /
  awk '$2 == "/" || $2 == "/var/log" { print }' /proc/mounts
)
```

The root should be `ro` and `/var/log` should be tmpfs again. A busy unmount or
failed read-only remount needs investigation; do not force it. Copy the now
quiescent capture to the Mac with the archive block above. Then start the four
existing TBot services again in step 4's ownership order, or perform a normal
orderly reboot. No fstab or runlevel change needs undoing. Retain the capture
until the outage is understood; do not enable another cloud run automatically.

References: [board runtime and read-only root](components/board.md),
[MicroVM evidence](agent-microvm-acceptance.md),
[BusyBox mount/syslog/klogd/sync](https://busybox.net/downloads/BusyBox.html),
[BusyBox tail options](https://github.com/mirror/busybox/blob/master/coreutils/tail.c).
