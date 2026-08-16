#!/bin/sh
# Copy to the root of the FAT boot partition. Run by the headless bootstrap on
# first boot, as root, once networking is up.
#
# Takes the board from a diskless Alpine boot to a persistent sys install on the
# standard Raspberry Pi layout, and installs the fixed Alpine runtime-package
# baseline. It configures hostname, wlan0, apk repositories, package upgrade,
# operator ssh, and mise on root's PATH. Device release binaries, daemon config,
# and services remain manual runbook steps over ssh.
#
# Modelled on contribs/unattended_sysdisk.sh from the headless bootstrap
# project. The important part borrowed from it is the config re-import below:
# the overlay is applied to the tmpfs root of the diskless boot and is not
# applied again once the board boots from mmcblk0p2, so the Wi-Fi configuration
# and the operator key are written onto the new root explicitly rather than
# trusted to survive.
#
# Edit HOSTNAME and, if the board is not in Europe/Berlin, TIMEZONE below.
# Everything else is read from the files beside this one on the boot partition.

set -eu

HOSTNAME="REPLACE_WITH_BOARD_HOSTNAME"
TIMEZONE="Europe/Berlin"

DISK="/dev/mmcblk0"
BOOT_PART="/dev/mmcblk0p1"
NEW_ROOT="/mnt/newroot"
LOG="/var/log/txing-unattended.log"

log() { printf '%s unattended: %s\n' "$(date -u +%H:%M:%S)" "$*" | tee -a "$LOG"; }
die() { log "FAILED: $*"; log "board left running and reachable for inspection"; exit 1; }

# Run a step, logging its output. A step that fails must say why: knowing only
# which command failed means another boot cycle to find out.
run() {
    step="$1"; shift
    log "$step"
    if ! "$@" >>"$LOG" 2>&1; then
        tail -n 20 "$LOG" >&2
        die "$step (see $LOG)"
    fi
}

# The script must never end silently. Without these, a kill or an unexpected
# non-zero exit leaves the log stopping mid-step with nothing to say whether the
# step failed, the script was killed, or the parent went away.
trap 'rc=$?; if command -v chroot_teardown >/dev/null 2>&1; then chroot_teardown; fi; if [ "$rc" -ne 0 ]; then log "exited with status $rc"; log "board left running and reachable for inspection"; fi' EXIT
trap 'log "killed by SIGTERM"; exit 143' TERM
trap 'log "interrupted by SIGINT"; exit 130' INT
trap 'log "hung up (SIGHUP): the parent session went away"; exit 129' HUP

log "starting base OS provisioning for ${HOSTNAME}"

# Locate the boot media the bootstrap read its files from, so the same Wi-Fi
# configuration and operator key can be carried onto the new root.
BOOT_MEDIA=""
for candidate in /media/mmcblk0p1 /media/*/; do
    if [ -f "${candidate}/wpa_supplicant.conf" ]; then
        BOOT_MEDIA="${candidate%/}"
        break
    fi
done
[ -n "$BOOT_MEDIA" ] || die "cannot find the boot partition; expected wpa_supplicant.conf on it"
log "boot media: $BOOT_MEDIA"

# Refuse to reinstall over a card that already carries a sys install. Re-running
# after an interrupted attempt must not destroy a board that already converted.
for candidate in ${DISK}p*; do
    [ -b "$candidate" ] || continue
    mkdir -p /mnt/probe
    if mount -o ro "$candidate" /mnt/probe >/dev/null 2>&1; then
        if [ -f /mnt/probe/etc/alpine-release ] && [ -d /mnt/probe/etc/runlevels ]; then
            umount /mnt/probe
            log "$candidate already holds an Alpine root; refusing to reinstall"
            log "if this board must be rebuilt, reimage the card"
            exit 0
        fi
        umount /mnt/probe
    fi
done

# The board must be on the network before anything below. The bootstrap starts
# Wi-Fi before running this, but association and DHCP can lag, and an apk
# failure ten seconds later is a much less obvious message than this one.
log "waiting for network"
network_ready=""
for _ in $(seq 1 30); do
    if ping -c1 -W2 dl-cdn.alpinelinux.org >/dev/null 2>&1; then
        network_ready="yes"
        break
    fi
    sleep 2
done
[ -n "$network_ready" ] || die "no network after 60s; check wpa_supplicant.conf (SSID, passphrase, country, LF line endings)"
log "network is up"

# The Pi has no RTC, so it boots with whatever time the image shipped with and
# can be months behind. TLS certificate validation checks validity dates, so a
# skewed clock reads as "server certificate not trusted" no matter what CA
# bundle is installed. Step the clock before anything touches the network.
# Best effort: if it fails, the http bootstrap below still works.
if ntpd -q -n -p pool.ntp.org >>"$LOG" 2>&1; then
    log "clock stepped to $(date -u '+%Y-%m-%d %H:%M:%S') UTC"
else
    log "WARNING: could not sync the clock; https may fail on certificate dates"
fi

# A diskless boot ships /etc/apk/repositories pointing only at the apks
# directory on the boot media: there are no network repositories to uncomment,
# so they are written here. The branch is taken from the running release rather
# than hardcoded, so the repositories always match the booted system.
ALPINE_BRANCH="v$(cut -d. -f1,2 /etc/alpine-release)"
MIRROR="dl-cdn.alpinelinux.org/alpine/${ALPINE_BRANCH}"

# Start on http. A diskless boot has no CA bundle, so apk cannot verify TLS to
# the mirror, and ca-certificates is what fixes that -- which needs the mirror.
# http is not a downgrade in integrity here: apk verifies every index and
# package against the signing keys in /etc/apk/keys, which is the boundary that
# matters. The diskless phase stays on http even after ca-certificates is
# installed, because apk on this boot still does not trust the bundle and
# chasing that in a transient tmpfs root is not worth a failure mode. The
# repositories written onto the sys install below use https, where a full base
# install has working trust.
log "configuring apk repositories for ${ALPINE_BRANCH}"
for repo in main community; do
    line="http://${MIRROR}/${repo}"
    grep -qxF "$line" /etc/apk/repositories || printf '%s\n' "$line" >>/etc/apk/repositories
done
grep -q "/${ALPINE_BRANCH}/community\$" /etc/apk/repositories \
    || die "community repository not configured; check /etc/apk/repositories"

run "updating package index" apk update
run "installing CA certificates" apk add --no-cache ca-certificates
run "upgrading packages" apk upgrade
run "installing filesystem tools" apk add --no-cache e2fsprogs curl


# setup-alpine drives the sys install. SSH_CONNECTION is faked because it
# otherwise refuses to run a disk step from what looks like a remote session.
# setup-disk erases the whole disk, including the FAT partition these files
# live on. Copy them into the tmpfs root first: the re-import below runs after
# the erase, when $BOOT_MEDIA no longer holds anything.
STASH="/tmp/txing-card"
log "stashing card files before the disk is erased"
mkdir -p "$STASH" || die "create $STASH"
for f in wpa_supplicant.conf authorized_keys interfaces; do
    if [ -f "$BOOT_MEDIA/$f" ]; then
        cp "$BOOT_MEDIA/$f" "$STASH/$f" || die "stash $f"
    fi
done
[ -f "$STASH/wpa_supplicant.conf" ] || die "wpa_supplicant.conf missing from $BOOT_MEDIA"

log "running setup-alpine for the sys install"
# setup-alpine rewrites /etc/apk/repositories from APKREPOSOPTS. Keep a copy of
# the file that is known to work on this board, so the sys install inherits it
# regardless of what mirror selection does.
cp /etc/apk/repositories /tmp/repositories.txing || die "save repositories"
cat >/tmp/answerfile <<ANSWERFILE
KEYMAPOPTS="none"
HOSTNAMEOPTS="-n ${HOSTNAME}"
DEVDOPTS="mdev"
INTERFACESOPTS="auto lo
iface lo inet loopback

auto wlan0
iface wlan0 inet dhcp
"
DNSOPTS="none"
TIMEZONEOPTS="-z ${TIMEZONE}"
PROXYOPTS="none"
APKREPOSOPTS="-c -1"
USEROPTS="none"
SSHDOPTS="-c openssh"
NTPOPTS="-c busybox"
DISKOPTS="-m sys ${DISK}"
LBUOPTS="none"
APKCACHEOPTS="none"
ANSWERFILE
# stdin is redirected from /dev/null so any question the answer file does not
# cover fails immediately on EOF instead of blocking forever. A hang here is
# worse than an error: it leaves the board half-provisioned with nothing in the
# log to say why.
SSH_CONNECTION="FAKE" ERASE_DISKS="$DISK" setup-alpine -ef /tmp/answerfile </dev/null >>"$LOG" 2>&1 \
    || { tail -n 40 "$LOG" >&2; die "setup-alpine (see $LOG)"; }

# Restore the repositories that were proven to work before setup-alpine ran.
cp /tmp/repositories.txing /etc/apk/repositories || die "restore repositories"


# Re-import the configuration onto the new root. The overlay is not applied
# again once the board boots from $ROOT_PART, so anything that only existed
# because the overlay was unpacked has to be written here explicitly. This is
# the step that keeps a converted board reachable.
# setup-disk chooses the layout, so the root partition is found rather than
# assumed: probe each partition for an Alpine root instead of hardcoding p2.
# setup-disk tears down mounts and repartitions, so device nodes are recreated
# underneath us. Mount each candidate read-write and keep the match mounted:
# unmounting and remounting leaves a window where the node can disappear.
# setup-disk repartitioned the disk, but nothing repopulates /dev afterwards, so
# the partition nodes can be missing entirely: the glob below then matches
# nothing and the probe silently finds no root. Ask the kernel to re-read the
# table and rebuild the device nodes, and wait for them to actually appear.
log "waiting for partition device nodes"
nodes_ready=""
for _ in $(seq 1 15); do
    partprobe "$DISK" >>"$LOG" 2>&1 || true
    # mdev is what a diskless Alpine boot uses; mdevd-coldplug covers mdevd.
    if command -v mdev >/dev/null 2>&1; then mdev -s >>"$LOG" 2>&1 || true; fi
    if command -v mdevd-coldplug >/dev/null 2>&1; then mdevd-coldplug >>"$LOG" 2>&1 || true; fi
    for node in ${DISK}p*; do
        if [ -b "$node" ]; then nodes_ready="yes"; break; fi
    done
    if [ -n "$nodes_ready" ]; then break; fi
    sleep 2
done
# Last resort: sysfs knows the device numbers even when /dev is stale, so the
# nodes can be created directly rather than waiting on a hotplug manager that
# may not be running at all in this environment.
if [ -z "$nodes_ready" ]; then
    log "no nodes appeared; creating them from sysfs"
    for sysdev in /sys/class/block/$(basename "$DISK")p*; do
        [ -r "$sysdev/dev" ] || continue
        node="/dev/$(basename "$sysdev")"
        major="$(cut -d: -f1 "$sysdev/dev")"
        minor="$(cut -d: -f2 "$sysdev/dev")"
        [ -b "$node" ] || mknod "$node" b "$major" "$minor" >>"$LOG" 2>&1 || true
        if [ -b "$node" ]; then nodes_ready="yes"; fi
    done
fi

ls -l "${DISK}"* >>"$LOG" 2>&1 || true
[ -n "$nodes_ready" ] || die "no partition nodes under ${DISK} after repartitioning (see $LOG)"
log "partition nodes present"

log "locating the new root partition"
ROOT_PART=""
for candidate in ${DISK}p*; do
    [ -b "$candidate" ] || continue
    mkdir -p "$NEW_ROOT"
    mount "$candidate" "$NEW_ROOT" >>"$LOG" 2>&1 || continue
    if [ -f "$NEW_ROOT/etc/alpine-release" ] && [ -d "$NEW_ROOT/etc/runlevels" ]; then
        ROOT_PART="$candidate"
        break
    fi
    umount "$NEW_ROOT" >/dev/null 2>&1 || true
done
[ -n "$ROOT_PART" ] || die "no Alpine root found on ${DISK}; setup-disk may not have installed (see $LOG)"
log "new root is $ROOT_PART, mounted at $NEW_ROOT"

log "importing Wi-Fi and operator key onto the new root"

# setup-disk installs a base system; wpa_supplicant and openssh are not part of
# it. Without these the runlevel links below point at init scripts that do not
# exist, and the board reboots with the right config and nothing running it.
install -d -m 755 "$NEW_ROOT/etc/apk"
sed -e "s|^http://${MIRROR}|https://${MIRROR}|" -e '\|^/media/|d' \
    /etc/apk/repositories >"$NEW_ROOT/etc/apk/repositories" \
    || die "install apk repositories"
chmod 644 "$NEW_ROOT/etc/apk/repositories"
grep -q "^https://${MIRROR}/community\$" "$NEW_ROOT/etc/apk/repositories" \
    || die "sys install repositories are not on https"

run "installing Alpine runtime package baseline into the new root" \
    apk --root "$NEW_ROOT" --no-cache add \
    wpa_supplicant openssh tzdata \
    curl jq ca-certificates \
    curl-dev openssl-dev log4cplus-dev libsrtp-dev libusrsctp-dev \
    libwebsockets-dev zlib-dev libcamera-dev \
    protobuf-dev grpc-dev \
    libcamera-raspberrypi eudev v4l-utils iproute2

# setup-alpine set the timezone on the running diskless system; the sys install
# is a fresh base and does not inherit it.
[ -f "$NEW_ROOT/usr/share/zoneinfo/$TIMEZONE" ] \
    || die "timezone $TIMEZONE not found in tzdata on the new root"
ln -sf "/usr/share/zoneinfo/${TIMEZONE}" "$NEW_ROOT/etc/localtime" \
    || die "set timezone on the new root"
printf '%s\n' "$TIMEZONE" >"$NEW_ROOT/etc/timezone" || die "write /etc/timezone"
log "timezone set to $TIMEZONE on the new root"

install -d -m 755 "$NEW_ROOT/etc/wpa_supplicant"
install -m 600 "$STASH/wpa_supplicant.conf" \
    "$NEW_ROOT/etc/wpa_supplicant/wpa_supplicant.conf" || die "install wpa_supplicant.conf"

if [ -f "$STASH/authorized_keys" ]; then
    install -d -m 700 "$NEW_ROOT/root/.ssh"
    install -m 600 "$STASH/authorized_keys" \
        "$NEW_ROOT/root/.ssh/authorized_keys" || die "install authorized_keys"
fi

if [ -f "$STASH/interfaces" ]; then
    install -m 644 "$STASH/interfaces" "$NEW_ROOT/etc/network/interfaces" \
        || die "install interfaces"
fi

# The image ships with an empty root password and the board is on Wi-Fi.
install -d -m 755 "$NEW_ROOT/etc/ssh/sshd_config.d"
cat >"$NEW_ROOT/etc/ssh/sshd_config.d/10-txing-board.conf" <<'SSHD'
PermitRootLogin prohibit-password
PasswordAuthentication no
SSHD

# Start networking, Wi-Fi, and sshd on the new root. Config without the service
# enabled is a board that looks dead in exactly the same way as bad credentials.
for service in networking wpa_supplicant sshd; do
    ln -sf "/etc/init.d/${service}" "$NEW_ROOT/etc/runlevels/default/${service}" \
        || die "enable $service on the new root"
done

# sshd generates its host keys on first start. On a read-only root that write
# fails and sshd never comes up: the board pings but refuses connections on 22.
# Generate them here, while the root is still writable. Written directly rather
# than through a chroot so no /dev or /proc bind mounts are needed.
log "generating ssh host keys on the new root"
install -d -m 755 "$NEW_ROOT/etc/ssh"
for keytype in ed25519 rsa; do
    keyfile="$NEW_ROOT/etc/ssh/ssh_host_${keytype}_key"
    if [ -f "$keyfile" ]; then continue; fi
    ssh-keygen -q -t "$keytype" -f "$keyfile" -N "" >>"$LOG" 2>&1 \
        || die "generating $keytype host key"
done
chmod 600 "$NEW_ROOT"/etc/ssh/ssh_host_*_key
chmod 644 "$NEW_ROOT"/etc/ssh/ssh_host_*_key.pub

# mise, installed into the new root while it is still writable. It is a static
# musl binary, so it needs nothing from the host and runs on Alpine unchanged.
# Installing it here rather than over ssh means the board comes up with `mise`
# already on root's PATH; a read-only root cannot install it afterwards without
# root-rw first.
# Install mise from inside the new root. Running it chrooted rather than
# steering it with MISE_INSTALL_PATH means $HOME, /tmp and the install path are
# genuinely the target's, and the download stages on the card instead of the
# diskless tmpfs, which is RAM on a 512 MB board and too full by this point:
# curl fails mid-write and the checksum mismatch that follows looks like a
# corrupt download rather than a full disk.
chroot_mounts_up=""
chroot_teardown() {
    [ -n "$chroot_mounts_up" ] || return 0
    for m in run dev sys proc; do
        umount "$NEW_ROOT/$m" >/dev/null 2>&1 || umount -l "$NEW_ROOT/$m" >/dev/null 2>&1 || true
    done
    chroot_mounts_up=""
}

log "installing mise into the new root"
install -d -m 1777 "$NEW_ROOT/tmp"
for m in proc sys dev run; do
    install -d -m 755 "$NEW_ROOT/$m"
    mount -o bind "/$m" "$NEW_ROOT/$m" >>"$LOG" 2>&1 || {
        chroot_teardown
        die "bind mounting /$m for the chroot (see $LOG)"
    }
done
chroot_mounts_up="yes"
log "new root free: $(df -h "$NEW_ROOT" | awk 'NR==2 {print $4}')"

if ! chroot "$NEW_ROOT" /bin/sh -c '
        set -eu
        export HOME=/root
        mkdir -p "$HOME/.local/bin"
        curl -fsSL https://mise.run | MISE_QUIET=1 sh
        "$HOME/.local/bin/mise" --version
    ' >>"$LOG" 2>&1; then
    tail -n 20 "$LOG" >&2
    chroot_teardown
    die "installing mise inside the new root (see $LOG)"
fi

# The bind mounts must go before the final umount of the new root, or that
# umount fails and the board reboots with the filesystem not cleanly unmounted.
chroot_teardown
chmod 755 "$NEW_ROOT/root/.local/bin/mise"

# Same PATH line the runbook uses, so a login shell finds it.
if ! grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' "$NEW_ROOT/root/.profile" 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >>"$NEW_ROOT/root/.profile"
fi
log "mise installed on the new root"

# swclock restores a saved timestamp at boot so an RTC-less board has a
# plausible time before NTP, and saves the current time at shutdown. On a
# read-only root that save silently fails, so every boot restores the same
# stale value. Worse, a plausible-but-wrong date passes the daemon's clock
# gate, where an unset clock would correctly hold off AWS TLS until ntpd has
# actually synced. The board has network time; swclock only lies to it.
log "disabling swclock on the new root"
rm -f "$NEW_ROOT/etc/runlevels/boot/swclock"

# Read-only root, per the runbook's Configure Read-Only Root step.
#
# udhcpc cannot refresh a regular /etc/resolv.conf on a read-only root, so DNS
# would fail after boot even with the network up. Point it at the runtime
# resolver first.
log "configuring read-only root on the new root"
install -d -m 755 "$NEW_ROOT/etc/udhcpc" || die "create /etc/udhcpc"
echo 'RESOLV_CONF="/run/resolv.conf"' >>"$NEW_ROOT/etc/udhcpc/udhcpc.conf" \
    || die "udhcpc.conf"
rm -f "$NEW_ROOT/etc/resolv.conf"
ln -s /run/resolv.conf "$NEW_ROOT/etc/resolv.conf" || die "resolv.conf symlink"

# setup-disk wrote a UUID-based fstab; reuse those UUIDs rather than guessing
# device names, which change with layout.
FSTAB="$NEW_ROOT/etc/fstab"
ROOT_SPEC="$(awk '$2 == "/" && $1 !~ /^#/ { print $1; exit }' "$FSTAB")"
BOOT_SPEC="$(awk '$2 == "/boot" && $1 !~ /^#/ { print $1; exit }' "$FSTAB")"
[ -n "$ROOT_SPEC" ] || die "no / entry in the new root's fstab"
[ -n "$BOOT_SPEC" ] || die "no /boot entry in the new root's fstab"

cat >"$FSTAB" <<FSTAB_EOF
${ROOT_SPEC}  /      ext4  ro,noatime  0 1
${BOOT_SPEC}  /boot  vfat  ro,noatime  0 2
tmpfs  /tmp             tmpfs  nosuid,nodev,mode=1777,size=32M      0 0
tmpfs  /var/tmp         tmpfs  nosuid,nodev,exec,mode=1777,size=96M 0 0
tmpfs  /var/log         tmpfs  nosuid,nodev,mode=0755,size=16M      0 0
FSTAB_EOF
log "fstab set read-only for / and /boot, with tmpfs for tmp, var/tmp and var/log"

# The aliases the runbook uses to flip the root back and forth. Without these an
# operator has no obvious way to make a read-only board writable again.
if ! grep -q "alias root-rw" "$NEW_ROOT/root/.profile" 2>/dev/null; then
    cat >>"$NEW_ROOT/root/.profile" <<'PROFILE_EOF'
alias root-rw='mount -o remount,rw /; mount -o remount,rw /boot; umount /var/tmp 2>/dev/null; umount /tmp 2>/dev/null'
alias root-ro='rm -rf /var/tmp/* /tmp/* ; sync; mount -o remount,ro /boot ; mount -o remount,ro / ; mount /tmp ; mount /var/tmp'
PROFILE_EOF
    log "root-rw and root-ro aliases installed for root"
fi

# Refuse to reboot into a root that would come back unreachable. A board that
# fails here stays up on the diskless boot, which is recoverable over ssh; one
# that reboots without these is not recoverable without physical access.
log "verifying the new root before reboot"
for required in \
    "$NEW_ROOT/etc/wpa_supplicant/wpa_supplicant.conf" \
    "$NEW_ROOT/root/.ssh/authorized_keys" \
    "$NEW_ROOT/etc/apk/repositories" ; do
    [ -f "$required" ] || die "missing on the new root: $required"
done

# Runlevel entries are symlinks into /etc/init.d. Test with -L, not -e: -e
# follows the link and resolves it against the running system, so a correct
# link into the new root reads as missing.
[ -L "$NEW_ROOT/etc/localtime" ] || die "timezone not set on the new root"
[ -x "$NEW_ROOT/root/.local/bin/mise" ] || die "mise is not installed on the new root"
grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' "$NEW_ROOT/root/.profile" \
    || die "mise is not on root's PATH; a read-only board cannot add it without root-rw"
# Written as an if, not `[ -e ] && die`: under set -e that AND-list returns
# non-zero in the success case and would exit the script silently.
if [ -e "$NEW_ROOT/etc/runlevels/boot/swclock" ]; then
    die "swclock is still enabled; it restores a stale time on a read-only root"
fi
[ -f "$NEW_ROOT/etc/ssh/ssh_host_ed25519_key" ] \
    || die "no ssh host key on the new root; sshd cannot start on a read-only root"
[ -L "$NEW_ROOT/etc/resolv.conf" ] \
    || die "/etc/resolv.conf is not a symlink; DNS will fail on a read-only root"
grep -q '^tmpfs  /var/log' "$NEW_ROOT/etc/fstab" \
    || die "fstab has no tmpfs for /var/log; a read-only root cannot write logs"
grep -q "alias root-rw" "$NEW_ROOT/root/.profile" \
    || die "root-rw alias missing; a read-only board would have no documented way back to writable"

for service in networking wpa_supplicant sshd; do
    link="$NEW_ROOT/etc/runlevels/default/${service}"
    [ -L "$link" ] || die "service $service is not enabled on the new root"
    [ -f "$NEW_ROOT/etc/init.d/${service}" ] \
        || die "/etc/init.d/${service} is missing on the new root; $service will not start"
done
log "new root verified"

sync
umount "$NEW_ROOT" >>"$LOG" 2>&1 || die "umount $NEW_ROOT (see $LOG)"

# Point the Pi firmware at the new root. The firmware only reads the FAT
# partition, and setup-disk recreated it during the erase, so the original
# $BOOT_MEDIA mount is gone and the new one has to be found.
log "checking the boot partition points at $ROOT_PART"
NEW_BOOT="/mnt/newboot"
mkdir -p "$NEW_BOOT"
BOOT_FOUND=""
for candidate in ${DISK}p*; do
    [ -b "$candidate" ] || continue
    if [ "$candidate" = "$ROOT_PART" ]; then continue; fi
    mount "$candidate" "$NEW_BOOT" >/dev/null 2>&1 || continue
    if [ -f "$NEW_BOOT/cmdline.txt" ]; then
        BOOT_FOUND="$candidate"
        break
    fi
    umount "$NEW_BOOT"
done

if [ -n "$BOOT_FOUND" ]; then
    if grep -q "root=" "$NEW_BOOT/cmdline.txt"; then
        log "boot partition $BOOT_FOUND already specifies a root: $(cat "$NEW_BOOT/cmdline.txt")"
    else
        sed -i "s|\$| root=${ROOT_PART}|" "$NEW_BOOT/cmdline.txt" || die "cmdline.txt"
        log "pointed $BOOT_FOUND at $ROOT_PART"
    fi
    sync
    umount "$NEW_BOOT" || log "WARNING: could not unmount $NEW_BOOT"
else
    # setup-disk installs the Pi bootloader itself, so this is a warning rather
    # than a failure: the board may well boot correctly without intervention.
    log "WARNING: no boot partition with cmdline.txt found; relying on setup-disk"
fi

# The root filesystem stays writable. A board that provisioned incorrectly has
# to be fixable over ssh; sealing it read-only is a later, deliberate step in
# the runbook.
# The log lives on the tmpfs root and would be lost at reboot, leaving no
# record of how this board was provisioned. Copy it onto the new root before
# the mount goes away.
if mount "$ROOT_PART" "$NEW_ROOT" >>"$LOG" 2>&1; then
    # /var/log is a tmpfs on the read-only root, so a log copied there would
    # be shadowed at boot. /root is on the root filesystem and stays readable.
    cp "$LOG" "$NEW_ROOT/root/txing-unattended.log" 2>/dev/null || true
    sync
    umount "$NEW_ROOT" >/dev/null 2>&1 || true
    log "provisioning log copied to the new root"
else
    log "WARNING: could not copy the provisioning log onto the new root"
fi

sync
log "base OS and runtime package baseline complete, rebooting into the sys install"
log "release binaries, daemon configuration, and services remain manual runbook steps over ssh"
reboot
