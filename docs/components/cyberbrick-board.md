# Cyberbrick Board

The cyberbrick board is the device-side Raspberry Pi Zero 2 W for the
`cyberbrick` device type. It runs the root-owned Go `txing-cyberbrick-daemon`
plus the native `txing-cyberbrick-kvs-master` and
`txing-cyberbrick-hardware-worker` on Alpine Linux aarch64, with all three
daemons dynamically linked against musl, supervised by OpenRC, on a read-only
root filesystem.

Cyberbrick board behavior is unit parity by design: the same board/mcp/video
shadows, retained topics, REDCON contract, BoardVideoBridge and hardware
worker contracts, MCP tool surface, and active-control rules documented in
[Board](./board.md). Intentional divergence from unit is limited to the OS
(Alpine instead of Raspberry Pi OS), the ABI (musl-dynamic instead of
unit's linkage), and init (OpenRC instead of systemd). This runbook documents
the cyberbrick identifiers and the Alpine-specific install, service, and
maintenance workflow.

## Cyberbrick Identifiers

Renamed surfaces relative to unit:

- binaries: `txing-cyberbrick-daemon`, `txing-cyberbrick-kvs-master`,
  `txing-cyberbrick-hardware-worker`
- config dir: `/root/.config/txing/cyberbrick-daemon/`
- daemon sockets: `/run/txing-cyberbrick-daemon/board-video-bridge.sock` and
  `/run/txing-cyberbrick-daemon/mcp-webrtc.sock`
- hardware worker socket:
  `/run/txing-cyberbrick-hardware-worker/cyberbrick-hardware.sock`
- proto packages: `txing.cyberbrick.hardware.v1` (service
  `CyberbrickHardware`) and `txing.cyberbrick.board_video.v1`
- adapter ID: `dev.txing.cyberbrick.Daemon`

Generic env keys (`TXING_MOTOR_*`, `TXING_BOARD_VIDEO_*`,
`TXING_HARDWARE_WORKER_*`, ...) keep the same names as unit; only
cyberbrick-specific path values change. The video signaling channel keeps the
repo-wide `<device_id>-board-video` shape. The cyberbrick board video contract
is documented in
[devices/cyberbrick/docs/board-video.md](../../devices/cyberbrick/docs/board-video.md).

## OS And ABI Contract

- Alpine Linux aarch64 on Raspberry Pi Zero 2 W, **sys install**
  (`setup-disk -m sys`), device apk repositories on the Alpine `v3.23` branch.
- Default Alpine stack: apk, ifupdown-ng + wpa_supplicant + udhcpc
  networking, chronyd time sync, OpenRC init. No systemd and no
  NetworkManager on the board.
- Every shipped binary is dynamically linked against musl. A healthy install
  shows the `/lib/ld-musl-aarch64.so.1` interpreter and fully resolved `ldd`
  output for all three binaries.
- The KVS master links Alpine's upstream libcamera and must resolve
  `libcamera.so.0.6` and `libcamera-base.so.0.6`. If `ldd` reports `not
  found` libraries or a non-musl interpreter, the release asset was built for
  the wrong OS or the wrong Alpine branch and must be replaced.
- The pinned Alpine build image in the cyberbrick daemon justfile, the
  release workflow containers, and the on-device apk branch must name the
  same Alpine release. Bumping the Alpine release is one coordinated change
  across all three plus a new cyberbrick release; see
  [Maintenance](#maintenance).

## Release Artifacts

Cyberbrick boards install three GitHub Release assets from the immutable
`cyberbrick-v*` release stream through root-owned `mise`:

```text
txing-cyberbrick-daemon-linux-aarch64.tar.gz
txing-cyberbrick-kvs-master-linux-aarch64.tar.gz
txing-cyberbrick-hardware-worker-linux-aarch64.tar.gz
```

Each archive contains one root-level executable with the same command name.
Boards use root's persistent mise config and install tree:

```text
/root/.config/mise/conf.d/txing-cyberbrick-daemon.toml
/root/.local/share/mise/installs/txing-cyberbrick-daemon/latest/txing-cyberbrick-daemon
/root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master
/root/.local/share/mise/installs/txing-cyberbrick-hardware-worker/latest/txing-cyberbrick-hardware-worker
```

Root-owned `mise` configs must set `version_prefix = "cyberbrick-v"` so
`latest` resolves from `cyberbrick-v*` GitHub Releases instead of the
repository-wide latest release. Service starts are offline by design:
restarting an OpenRC service does not install or upgrade tools, invoke mise,
or call GitHub. If a board needs new binaries, follow
[Maintenance](#maintenance).

## Fresh Board Install

Assumptions:

- Raspberry Pi Zero 2 W
- Alpine Linux aarch64 Raspberry Pi image from the `v3.23` branch
- AWS resources and the target cyberbrick thing already exist
  (`just aws::deploy` once per stack, then
  `just aws::deploy-device <raspi-rig-id> cyberbrick <name>`)
- daemon environment/certificate archive has been generated on the operator
  machine

### 1. Create The Card And Sys Install

Prepare the SD card on the operator machine with the Alpine `v3.23`
Raspberry Pi aarch64 image (`alpine-rpi-<version>-aarch64`) following the
Alpine Raspberry Pi imaging instructions, boot the board from it, and log in
on the console as `root` (empty password).

Run the interactive base setup:

```sh
setup-alpine
```

Answers that matter for a cyberbrick board:

- hostname: the thing id (for example `cyberbrick-bl95f2`)
- interface: `wlan0` with the deployment Wi-Fi SSID and passphrase
  (setup-alpine configures ifupdown-ng + wpa_supplicant + udhcpc), or `eth0`
  with a wired adapter
- NTP client: `chronyd` (the default)
- SSH server: `openssh`, with the operator public key installed for `root` so
  the remaining steps can run over SSH
- disk mode: `none` (the sys install target partition is created next)

The Raspberry Pi image boots diskless from the FAT partition. Convert the
same card to a persistent sys install:

```sh
apk add cfdisk e2fsprogs
cfdisk /dev/mmcblk0
setup-disk -m sys /dev/mmcblk0p2
```

In `cfdisk`, create one Linux partition (`/dev/mmcblk0p2`) in the free space
after the boot FAT partition and write the table before quitting. After
`setup-disk` finishes, point the boot FAT at the new root filesystem if
`setup-disk` did not already do it, then reboot into the sys install:

```sh
mount -o remount,rw /media/mmcblk0p1
grep -q 'root=/dev/mmcblk0p2' /media/mmcblk0p1/cmdline.txt \
  || sed -i 's|$| root=/dev/mmcblk0p2|' /media/mmcblk0p1/cmdline.txt
reboot
```

All remaining steps run as `root` on the sys install while the root
filesystem is still writable.

### 2. Install OS Packages

```sh
apk update
apk upgrade
apk add \
  curl jq ca-certificates \
  curl-dev openssl-dev log4cplus-dev libsrtp-dev libusrsctp-dev \
  libwebsockets-dev zlib-dev libcamera-dev \
  protobuf-dev grpc-dev
```

The dev packages are the proven runtime superset from the pinned Alpine build
container: installing them guarantees every shared library the musl-dynamic
release binaries resolve at run time, on the same `v3.23` branch the release
was built against. The manual install checks below run `ldd` on the resolved
binaries before the services are enabled. The release KVS master must link
`libcamera.so.0.6` and `libcamera-base.so.0.6` from Alpine `v3.23`; if the
sonames do not resolve, the installed apk branch and the release were built
against different Alpine releases and must be realigned first.

### 3. Install Mise

`mise` ships as a static musl binary and installs on Alpine unchanged:

```sh
mkdir -p "$HOME/.local/bin"
curl https://mise.run | sh
if ! grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.profile" 2>/dev/null; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile"
fi
/root/.local/bin/mise --version
```

### 4. Generate And Copy Daemon Config

On the operator machine:

```sh
just aws::cert <thing-id>
scp certs/<thing-id>/<thing-id>-daemon-config.tgz root@<board-host>:/tmp/<thing-id>-daemon-config.tgz
```

On the board:

```sh
install -d -m 700 "$HOME/.config/txing/cyberbrick-daemon"
tar --no-same-owner -xzf /tmp/<thing-id>-daemon-config.tgz -C "$HOME/.config/txing/cyberbrick-daemon"
chmod 700 "$HOME/.config/txing/cyberbrick-daemon"
chmod 600 "$HOME/.config/txing/cyberbrick-daemon/daemon.env"
chmod 600 "$HOME/.config/txing/cyberbrick-daemon/certificate.arn"
chmod 600 "$HOME/.config/txing/cyberbrick-daemon/certificate.pem.crt"
chmod 600 "$HOME/.config/txing/cyberbrick-daemon/private.pem.key"
chmod 600 "$HOME/.config/txing/cyberbrick-daemon/public.pem.key"
chmod 644 "$HOME/.config/txing/cyberbrick-daemon/AmazonRootCA1.pem"
rm -f /tmp/<thing-id>-daemon-config.tgz
```

`daemon.env` is rendered from
`devices/cyberbrick/daemon/daemon.env.template` and uses plain `KEY=value`
lines so both the daemon and the hardware worker init script can consume the
same root-owned file. Certificate paths are omitted by default; the daemon
derives colocated paths from the loaded `daemon.env` directory. For manual
shell export, use
`set -a; . /root/.config/txing/cyberbrick-daemon/daemon.env; set +a`.
Motor calibration, including
`TXING_MOTOR_LEFT_TRACK_POWER_PERCENT`/`TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT`
track trim, follows the unit board contract in [Board](./board.md).

If the device daemon role policy needs to be refreshed later (for example
after policy changes on the operator side), run this on the operator machine:

```sh
just cyberbrick::daemon::role-policy <thing-id>
```

### 5. Install Runtime And OpenRC Services

Install the release tools through root-owned `mise`:

```sh
install -d -m 700 /root/.config/mise/conf.d /root/.local/share/mise
cat >/root/.config/mise/conf.d/txing-cyberbrick-daemon.toml <<'EOF'
[settings]
fetch_remote_versions_cache = "10m"

[tool_alias]
txing-cyberbrick-daemon = "github:mparkachov/txing"
txing-cyberbrick-kvs-master = "github:mparkachov/txing"
txing-cyberbrick-hardware-worker = "github:mparkachov/txing"

[tools.txing-cyberbrick-daemon]
version = "latest"
version_prefix = "cyberbrick-v"
asset_pattern = "txing-cyberbrick-daemon-linux-aarch64.tar.gz"

[tools.txing-cyberbrick-kvs-master]
version = "latest"
version_prefix = "cyberbrick-v"
asset_pattern = "txing-cyberbrick-kvs-master-linux-aarch64.tar.gz"

[tools.txing-cyberbrick-hardware-worker]
version = "latest"
version_prefix = "cyberbrick-v"
asset_pattern = "txing-cyberbrick-hardware-worker-linux-aarch64.tar.gz"
EOF

MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise install txing-cyberbrick-daemon@latest txing-cyberbrick-kvs-master@latest txing-cyberbrick-hardware-worker@latest
```

Check the resolved binaries before writing the services. Every binary must
report the release version, use the musl interpreter, and resolve all shared
libraries:

```sh
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-cyberbrick-daemon/latest/txing-cyberbrick-daemon --version
/root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master --version
/root/.local/share/mise/installs/txing-cyberbrick-hardware-worker/latest/txing-cyberbrick-hardware-worker --version
ldd /root/.local/share/mise/installs/txing-cyberbrick-daemon/latest/txing-cyberbrick-daemon
ldd /root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master
ldd /root/.local/share/mise/installs/txing-cyberbrick-hardware-worker/latest/txing-cyberbrick-hardware-worker
ldd /root/.local/share/mise/installs/txing-cyberbrick-daemon/latest/txing-cyberbrick-daemon | grep -F "ld-musl-aarch64.so.1"
ldd /root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master | grep -F "libcamera.so.0.6"
ldd /root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master | grep -F "libcamera-base.so.0.6"
```

Write the root-owned OpenRC init scripts. There is no OpenRC equivalent of
unit's `txing-unit.target`; each service is enabled individually and OpenRC
dependencies order them hardware worker, then daemon, then KVS master. The
daemon owns the board-video bridge socket; the KVS master connects to it as a
separate service. The hardware worker owns the CyberbrickHardware socket; the
daemon connects to it as a client and degrades if it is unavailable. All
three services run under `supervise-daemon`, which restarts them on failure
with bounded respawn limits. The daemons exit cleanly on the default
supervise-daemon stop signal.

```sh
cat >/etc/init.d/txing-cyberbrick-hardware-worker <<'EOF'
#!/sbin/openrc-run

description="Txing Cyberbrick Hardware Worker"

supervisor=supervise-daemon
command=/root/.local/share/mise/installs/txing-cyberbrick-hardware-worker/latest/txing-cyberbrick-hardware-worker
directory=/root
respawn_delay=2
respawn_max=5
respawn_period=600
output_log=/var/log/txing-cyberbrick-hardware-worker.log
error_log=/var/log/txing-cyberbrick-hardware-worker.log

daemon_env=/root/.config/txing/cyberbrick-daemon/daemon.env

depend() {
    need localmount
    before txing-cyberbrick-daemon
}

start_pre() {
    test -x "$command" || return 1
    test -r "$daemon_env" || return 1
    checkpath --directory --mode 0755 --owner root:root /run/txing-cyberbrick-hardware-worker
    set -a
    . "$daemon_env"
    set +a
    export HOME=/root
}
EOF

cat >/etc/init.d/txing-cyberbrick-daemon <<'EOF'
#!/sbin/openrc-run

description="Txing Cyberbrick Daemon"

supervisor=supervise-daemon
command=/root/.local/share/mise/installs/txing-cyberbrick-daemon/latest/txing-cyberbrick-daemon
directory=/root
respawn_delay=5
respawn_max=5
respawn_period=600
output_log=/var/log/txing-cyberbrick-daemon.log
error_log=/var/log/txing-cyberbrick-daemon.log

depend() {
    need net
    use dns chronyd
    after txing-cyberbrick-hardware-worker
}

start_pre() {
    test -x "$command" || return 1
    checkpath --directory --mode 0755 --owner root:root /run/txing-cyberbrick-daemon
    if ! chronyc waitsync 60 0 0 3 >/dev/null 2>&1; then
        ewarn "clock is not confirmed synchronized; AWS TLS setup may retry"
    fi
    export HOME=/root
    export TXING_DAEMON_CONFIG_DIR=/root/.config/txing/cyberbrick-daemon
}
EOF

cat >/etc/init.d/txing-cyberbrick-kvs-master <<'EOF'
#!/sbin/openrc-run

description="Txing Cyberbrick Board KVS Master"

supervisor=supervise-daemon
command=/root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master
directory=/root
respawn_delay=5
respawn_max=5
respawn_period=600
output_log=/var/log/txing-cyberbrick-kvs-master.log
error_log=/var/log/txing-cyberbrick-kvs-master.log

depend() {
    need net
    use dns
    after txing-cyberbrick-daemon
}

start_pre() {
    test -x "$command" || return 1
    export HOME=/root
    export TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH=/run/txing-cyberbrick-daemon/board-video-bridge.sock
}
EOF

chmod 755 /etc/init.d/txing-cyberbrick-hardware-worker
chmod 755 /etc/init.d/txing-cyberbrick-daemon
chmod 755 /etc/init.d/txing-cyberbrick-kvs-master

rc-update add txing-cyberbrick-hardware-worker default
rc-update add txing-cyberbrick-daemon default
rc-update add txing-cyberbrick-kvs-master default
rc-service txing-cyberbrick-hardware-worker restart
rc-service txing-cyberbrick-daemon restart
rc-service txing-cyberbrick-kvs-master restart
```

Verify:

```sh
rc-status default
rc-service txing-cyberbrick-hardware-worker status
rc-service txing-cyberbrick-daemon status
rc-service txing-cyberbrick-kvs-master status
tail -n 160 /var/log/txing-cyberbrick-hardware-worker.log
tail -n 160 /var/log/txing-cyberbrick-daemon.log
tail -n 160 /var/log/txing-cyberbrick-kvs-master.log
```

Expected:

- all three services are `started` and stay up under `supervise-daemon`
- the daemon log includes `version=<release-version>`
- the daemon binds `/run/txing-cyberbrick-daemon/board-video-bridge.sock`
- the hardware worker binds
  `/run/txing-cyberbrick-hardware-worker/cyberbrick-hardware.sock`
- the worker logs version and local actuator readiness or a clear hardware
  error
- MQTT connects
- retained `board`, dynamic `mcp`, and `video` state is published
- the KVS master service reaches READY over the bridge when camera and
  signaling are available
- REDCON can reach `1` after Sparkplug projection sees fresh `board`, `mcp`,
  and `video` capability state

### 6. Enable PWM Overlay

Append this to `usercfg.txt` on the boot FAT partition (the stock Raspberry
Pi `config.txt` includes it) while the partition is writable:

```ini
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

The `pwm-2chan.dtbo` overlay ships in Alpine's `raspberrypi-bootloader`
content already present on the boot FAT partition. Restart after changing the
overlay so PWM devices exist before motor validation.

### 7. Configure Read-Only Root

The runtime is compatible with read-only root as long as these paths stay
writable on tmpfs:

- `/tmp`
- `/var/tmp`
- `/var/log`
- `/var/lib/chrony`

The native KVS worker keeps the signaling cache in memory and does not depend
on the SDK default `.SignalingCache_v1` file. chronyd tolerates a missing
drift file on the `/var/lib/chrony` tmpfs; it only costs a warning at boot.

Make `/etc/resolv.conf` point at udhcpc's runtime resolver output before
switching root to read-only. With a regular file on read-only root, udhcpc
cannot refresh resolver configuration after boot and DNS may fail even when
the network is otherwise online:

```sh
echo 'RESOLV_CONF="/run/resolv.conf"' >> /etc/udhcpc/udhcpc.conf
rm -f /etc/resolv.conf
ln -s /run/resolv.conf /etc/resolv.conf
readlink /etc/resolv.conf
rc-service networking restart
getent hosts example.com
```

Use this `fstab` layout (partition device names are stable in the Pi's SD
slot; verify with `lsblk` before writing):

```fstab
/dev/mmcblk0p1  /media/mmcblk0p1  vfat  defaults,ro,noatime  0 2
/dev/mmcblk0p2  /                 ext4  defaults,ro,noatime  0 1
tmpfs           /tmp              tmpfs nosuid,nodev,mode=1777,size=32M 0 0
tmpfs           /var/tmp          tmpfs nosuid,nodev,exec,mode=1777,size=96M 0 0
tmpfs           /var/log          tmpfs nosuid,nodev,mode=0755,size=16M 0 0
tmpfs           /var/lib/chrony   tmpfs nosuid,nodev,mode=0755,size=4M 0 0
```

Useful shell aliases:

```sh
cat >> /root/.profile <<'EOF'
alias root-rw='mount -o remount,rw /; mount -o remount,rw /media/mmcblk0p1; umount /var/tmp; umount /tmp'
alias root-ro='rm -rf /var/tmp/* /tmp/* ; sync; mount -o remount,ro /media/mmcblk0p1 ; mount -o remount,ro / ; mount /tmp ; mount /var/tmp'
EOF
```

Operational rules:

- do apk installs, `mise` installs/updates, daemon config changes, and
  OpenRC init script changes while root is writable
- switch back to read-only only after runtime binaries, native workers, and
  config files are in place
- the services run as root with `HOME=/root`
- AWS-backed services depend on net and wait for clock synchronization so TLS
  validation does not race NTP
- the hardware worker neutralizes motors internally; supervise-daemon restart
  latency is supervision only, not the motion-control safety layer

### 8. Final Reboot Check

```sh
root-ro
reboot
```

After reconnecting:

```sh
mount | grep ' / '
rc-status default
rc-service txing-cyberbrick-hardware-worker status
rc-service txing-cyberbrick-daemon status
rc-service txing-cyberbrick-kvs-master status
tail -n 160 /var/log/txing-cyberbrick-hardware-worker.log
tail -n 160 /var/log/txing-cyberbrick-daemon.log
tail -n 160 /var/log/txing-cyberbrick-kvs-master.log
/root/.local/bin/mise list
/root/.local/share/mise/installs/txing-cyberbrick-daemon/latest/txing-cyberbrick-daemon --version
/root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master --version
/root/.local/share/mise/installs/txing-cyberbrick-hardware-worker/latest/txing-cyberbrick-hardware-worker --version
readlink /etc/resolv.conf
getent hosts example.com
```

Expected:

- root filesystem is read-only
- `/etc/resolv.conf` points at `/run/resolv.conf` and DNS resolves through
  udhcpc
- all three services start under OpenRC without a source checkout and without
  network access to GitHub
- daemon log includes `version=<release-version>`
- MQTT connects and retained board/MCP/video state is published

First bring-up on a physical board must additionally confirm the video and
motor assumptions carried over from unit before declaring parity: camera
enumeration through Alpine's libcamera, the `/dev/video11` H.264 encoder
assumption, a short end-to-end H.264 capture, and both PWM channels moving
the motors. Record deviations as milestone findings instead of patching
around them.

## Maintenance

Board update during a writable-root maintenance window. Publish a new
immutable `cyberbrick-vX.Y.Z` release first.

Because the binaries are dynamically linked against musl and the installed
Alpine libraries, `apk upgrade` and `mise upgrade` happen together in the
same maintenance window: never upgrade the OS packages without moving to the
release built for them, and never install a release built against a newer
Alpine branch than the device runs. Device apk repositories stay on Alpine
`v3.23` until a coordinated bump.

```sh
root-rw
apk update
apk upgrade
MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise upgrade txing-cyberbrick-daemon txing-cyberbrick-kvs-master txing-cyberbrick-hardware-worker
/root/.local/share/mise/installs/txing-cyberbrick-daemon/latest/txing-cyberbrick-daemon --version
/root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master --version
/root/.local/share/mise/installs/txing-cyberbrick-hardware-worker/latest/txing-cyberbrick-hardware-worker --version
ldd /root/.local/share/mise/installs/txing-cyberbrick-daemon/latest/txing-cyberbrick-daemon
ldd /root/.local/share/mise/installs/txing-cyberbrick-hardware-worker/latest/txing-cyberbrick-hardware-worker
ldd /root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master | grep -F "libcamera.so.0.6"
ldd /root/.local/share/mise/installs/txing-cyberbrick-kvs-master/latest/txing-cyberbrick-kvs-master | grep -F "libcamera-base.so.0.6"
sync
reboot
```

Do not reboot if any `ldd` output reports `not found` or the expected
libcamera sonames are missing; realign the apk branch and the installed
release first, inside the same window.

If `apk upgrade` updated the kernel (`linux-rpi`) or the Raspberry Pi boot
firmware, sync the refreshed boot files from the kernel package onto the boot
FAT partition per Alpine's Raspberry Pi sys-install guidance before
rebooting; the Pi firmware only reads the FAT partition.

Bumping the Alpine release (for example a future move off `v3.23`, or a
libcamera soname change inside the branch) is one coordinated change: update
the pinned build image in the cyberbrick daemon justfile and the release
workflow containers, publish a matching cyberbrick release built on that
Alpine version, and only then move the device apk repositories and run the
coupled `apk upgrade` + `mise upgrade` window above.

## Local Development

Daemon and native board worker commands:

```sh
just cyberbrick::daemon::test
just cyberbrick::daemon::run
just cyberbrick::daemon::kvs-test-native
just cyberbrick::daemon::hardware-test-native
just cyberbrick::daemon::daemon-build-alpine
just cyberbrick::daemon::kvs-build-alpine
just cyberbrick::daemon::hardware-build-alpine
just cyberbrick::daemon::docker-build
```

The local daemon uses
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/cyberbrick-daemon}`.
Provision that directory with `just aws::cert <thing-id>` only when AWS
resource changes are intended.

The `*-build-alpine` and `docker-build` recipes build inside the pinned
Alpine aarch64 container and require a native `linux/arm64` Docker daemon.
They assert the musl interpreter, fully resolved shared libraries, and the
expected libcamera sonames on every produced binary — the same contract the
release workflow enforces.

## References

- [Board (canonical unit-parity behavior contract)](./board.md)
- [Artifacts](../artifacts.md)
- [Installation overview](../installation.md)
- [Cyberbrick board video contract](../../devices/cyberbrick/docs/board-video.md)
- [Board video bridge contract](../contracts/board-video-bridge.md)
- [Hardware worker contract](../contracts/unit-hardware-worker.md)
- [Sparkplug lifecycle](../sparkplug-lifecycle.md)
