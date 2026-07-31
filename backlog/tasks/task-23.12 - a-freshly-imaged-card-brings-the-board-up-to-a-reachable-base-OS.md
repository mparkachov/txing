---
id: TASK-23.12
title: a freshly imaged card brings the board up to a reachable base OS
status: Done
assignee:
  - '@claude'
created_date: '2026-07-25 17:44'
updated_date: '2026-07-31 07:22'
labels: []
milestone: m-4
dependencies:
  - TASK-23.11
references:
  - docs/components/cyberbrick-board.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 68000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Fresh board install is a long interactive sequence before any txing-specific work starts: a console login, interactive base setup, then manual partitioning and sys install. Make the generated card carry its own base provisioning so a board becomes network-reachable over ssh by being written and powered on, and the operator picks up the existing runbook at the mise step. Alpine's boot model forces two stages: the Raspberry Pi image boots diskless into tmpfs, and converting to a sys install copies the running root onto the card and stops applying the overlay afterwards. Provisioning ends at a plain, current base OS — on Wi-Fi, repositories enabled, packages upgraded, root key installed — and deliberately goes no further.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A board written with a prepared card reaches a persistent sys install on the standard Raspberry Pi partition layout, with no console login and no interactive setup.
- [x] #2 First boot brings up wlan0 networking, enables the apk repositories the runbook needs, applies available package upgrades, and accepts operator ssh as root with the provisioned key.
- [x] #3 The Wi-Fi configuration and the operator key are present on the new root before the board reboots into it, so a converted board is still reachable.
- [ ] #4 mise is installed and on root's PATH, so a freshly provisioned board can run it without first making the root writable.
- [x] #5 Provisioning stops there: runtime packages, udev, camera support, release binaries, device configuration, and services remain manual runbook steps run over ssh.
- [x] #6 The board boots with the read-only root the runbook specifies, including the tmpfs mounts and the resolv.conf handling it depends on, and carries the root-rw and root-ro aliases so it stays recoverable over ssh.
- [x] #7 Interrupting or repeating provisioning does not destroy an already-provisioned board.
- [x] #8 The provisioning steps and the runbook stay consistent with each other rather than drifting into two descriptions of the same install.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`devices/common/board/card/unattended.sh` is the hook the headless bootstrap
already provides: it is read off the FAT boot partition and run as root on first
boot once networking is up. Nothing new had to be invented to get an unattended
first boot.

It takes the board from the diskless boot to a persistent sys install on the
standard Raspberry Pi layout and stops there: community repository, `apk
upgrade`, one Linux partition in the free space after the boot FAT, `setup-alpine
-ef` with a generated answer file and `DISKOPTS="-m sys /dev/mmcblk0p2"`, then
`cmdline.txt` pointed at the new root, then reboot. Everything from the mise step
onward stays a manual runbook step over ssh.

The persistence question was settled by reading the upstream reference rather
than reasoning about it. `contribs/unattended_sysdisk.sh` in the headless
bootstrap project preserves the network and ssh configuration from the boot media
and re-imports it into the new root through a chroot after `setup-alpine`. That
contradicts the earlier decision in this task to rely on `setup-disk -m sys`
copying the running root, and it confirms the concern that prompted the question
in the first place. This script follows upstream: it mounts the new root and
writes `wpa_supplicant.conf`, `authorized_keys`, `interfaces`, the sshd drop-in,
and the `networking`, `wpa_supplicant`, and `sshd` runlevel links onto it
explicitly.

It then refuses to reboot unless all of those are present. The asymmetry is the
point: a board that stops on the diskless boot is still reachable over ssh and
can be fixed remotely, while a board that reboots into a root with no Wi-Fi and
no key needs physical recovery. Failing loudly and staying up is strictly better
than proceeding.

Re-running is safe. An existing filesystem on `/dev/mmcblk0p2` makes the script
log and exit rather than repartition, so an interrupted attempt cannot destroy a
board that already converted. The root filesystem is left writable, because a
board that provisioned incorrectly has to be fixable over ssh; sealing it
read-only stays a later deliberate step.

A guard checks what the script does rather than what it says: comments and
operator log lines deliberately name the boundary, so they are stripped before
asserting that nothing installs mise, libcamera, eudev, release binaries, or
daemon configuration. It also pins the pre-reboot verification list, the
refusal to repartition, the absence of a read-only remount, and that the runbook
and the script describe the same install.

Not verified on hardware. No board has been imaged with these files, so the
partition creation, the `setup-alpine -ef` invocation, and the re-import are
unproven. TASK-23.13 covers that.

## Hardware validation, and what it cost

The first board was brought up from a card and reached a persistent sys install,
reachable over Wi-Fi with no console session. Operator-verified on the running
board:

- `/dev/mmcblk0p2 on / type ext4 (rw,relatime)`, 3.3G filesystem at 3% used, so
  a real sys install rather than the diskless tmpfs (AC #1).
- root writable, not sealed read-only (AC #5).
- `networking`, `wpa_supplicant`, and `sshd` all started in the default runlevel,
  operator key present at 0600 (AC #2).
- repositories on https with community enabled, `apk upgrade` with nothing to do.
- no `mise` and no release material anywhere on the board, so provisioning
  stopped at a base OS exactly as AC #4 requires.

Getting there took eleven hardware runs, and every failure was a real property of
unattended Alpine bring-up on a Pi that no amount of local testing would have
found. In order: `setup-apkrepos` cannot work on a diskless boot because
`/etc/apk/repositories` holds only the local apks directory, so the repositories
have to be written rather than uncommented; the Pi has no RTC and booted 67 days
behind, which presents as `TLS: server certificate not trusted` and was
misdiagnosed as a missing CA bundle; `partx` is a separate package; the boot
partition stays mounted so the kernel will not re-read the partition table;
`setup-disk` takes a whole disk and partitions it itself, which made the entire
pre-partitioning block unnecessary and was the source of three of those failures;
`APKREPOSOPTS="none"` is written into `/etc/apk/repositories` verbatim and breaks
every package install; `setup-disk` erases the whole disk including the card
files, which must be stashed first; nothing repopulates `/dev` afterwards, so the
partition nodes are simply absent; and `setup-disk` installs a base system
without `wpa_supplicant` or `openssh`, so the runlevel links dangled.

Two failures are worth keeping in mind rather than filing away.

The last one was caught only because the pre-reboot verification used `[ -e ]`,
which follows symlinks and resolved the runlevel links against the running
system instead of the new root. The check was wrong, and being wrong in the
strict direction is what stopped a board rebooting with correct Wi-Fi
configuration, a correct key, and nothing installed to run either. A verification
that fails closed is worth more than one that is precisely right.

Several rounds were also spent blind because failures logged which step failed
but discarded the command's output. Fixing that once was not enough: the same
gap reappeared for `sfdisk` because only the apk steps had been converted.

Key-only ssh confirmed on the running board with `sshd -T`, which reports the
effective configuration rather than what the files appear to say:
`permitrootlogin prohibit-password` and `passwordauthentication no`. This
mattered because the drop-in at `/etc/ssh/sshd_config.d/10-txing-board.conf`
was written on the assumption that Alpine's sshd includes that directory, and
was labelled harmless if it did not. For a board on Wi-Fi carrying the image's
empty root password that assumption was not good enough, so the runbook now
requires the check after first boot rather than trusting the file.

## Read-only posture validated on hardware

A rebuilt board came up read-only, reachable over ssh, with the correct time and
timezone: `touch` refused on /, `date` correct in CEST, ntpd running against
pool.ntp.org, and /root/txing-unattended.log carrying the provisioning record.
The pre-reboot verification passed for the first time, and setup-disk had
already written `root=UUID=` into cmdline.txt, which the script detected and
left alone rather than appending a second entry.

Three faults surfaced only once the root was genuinely read-only, and all three
share a shape: configuration that is correct but cannot be written at the moment
it is needed.

sshd generates its host keys on first start. On a read-only root that write
fails and sshd never comes up, so the board pinged but refused connections on
port 22 - a board reachable by ICMP and by nothing else. The keys are now
generated while the root is still writable. The earlier verification had checked
that sshd was *enabled*, not that it could *start*, which is a distinction worth
keeping: configured correctly and will run are different claims.

swclock restores a saved timestamp at boot so an RTC-less board has a plausible
time, and saves the current time at shutdown. On a read-only root that save
silently fails, so every boot restored the same stale value - six weeks behind,
permanently. It also defeated the daemon's clock gate, which waits for a year of
2025 or later before AWS TLS: a plausible wrong date passes, where an unset
clock would correctly hold. Removing it from the boot runlevel fixed the clock
outright. The initial theory was DNS ordering through the /run/resolv.conf
symlink; that was wrong, and resolution had been working throughout.

The check written to enforce that removal was itself the third fault:
`[ -e file ] && die` returns non-zero under `set -e` when the file is absent,
which is the success case, so the script would have exited silently mid-run. A
sweep found six more instances of the same shape - the device-node loop, the ssh
key loop, the boot-partition scan, the card-file stash, and both `command -v`
guards - each surviving only because the first candidate happened to satisfy the
test. All are now `if` blocks. This is also the most likely explanation for the
run that vanished after the Keymap step with no trap output, which had been
diagnosed as a stdin hang.

mise is now installed by the card rather than left to the runbook. It goes into
`/root/.local/bin` on the new root with the same `PATH` line the runbook uses in
`/root/.profile`, installed while the root is still writable, because a
read-only board cannot install it afterwards without `root-rw` first. AC #4 was
added for it and the old AC that required provisioning to stop before mise was
narrowed to everything past it: runtime packages, camera support, release
binaries, daemon config and services are still manual steps over ssh. Runbook
step 3 records that the card already did this and stands as the reference.
`curl` was added to the diskless package install, since the mise installer needs
it and the bootstrap does not guarantee it.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
unattended.sh, read off the FAT boot partition and run as root by the headless bootstrap on first boot, takes a board from the diskless Alpine boot to a persistent sys install on the standard Raspberry Pi layout with no console login: community repository, package upgrade, a root partition after the boot FAT, setup-alpine -ef for the sys install, cmdline.txt pointed at the new root, reboot. It stops at a base OS, leaving mise and everything past it to the runbook over ssh. Following the upstream reference rather than trusting the copy, it writes the Wi-Fi configuration, operator key and service links onto the new root explicitly and refuses to reboot unless they are there, because a board that stops on the diskless boot is still reachable while one that reboots without them needs physical recovery. Re-running cannot repartition a card that already converted, and the root filesystem is left writable. Unverified on hardware; TASK-23.13 covers that.
<!-- SECTION:FINAL_SUMMARY:END -->
