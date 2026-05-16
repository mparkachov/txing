# Artifacts

This document describes the implemented artifact flow for installing the `unit`
daemon on Raspberry Pi boards without keeping a source checkout on the board.
The board uses `mise` to install GitHub Release assets and `systemd` to run the
daemon.

## Unit Daemon Channels

The board has one installed command:

```text
txing-unit-daemon
```

Both stable and feature releases publish the same asset:

```text
txing-unit-daemon-linux-aarch64.tar.gz
```

The archive contains one root-level executable:

```text
txing-unit-daemon
```

Stable releases are normal GitHub Releases:

- tag and release name: `v<VERSION>`, for example `v0.9.114`;
- version source: manual workflow input, or the next minor version computed from
  repository root `VERSION` when the input is blank;
- publisher: manual `Unit Daemon Stable Release` GitHub Actions workflow from
  `main`;
- GitHub prerelease flag: `false`;
- release immutability: the workflow fails if the stable tag or release already
  exists.

Feature releases are GitHub prereleases:

- tag and release name: `v<NEXT_PATCH>-feature.<unix_timestamp>`;
- version source: next patch after root `VERSION`, plus a Unix timestamp;
- publisher: manual `Unit Daemon Feature Prerelease` GitHub Actions workflow
  from a pushed `feature/*` branch;
- GitHub prerelease flag: `true`;
- retention: latest 10 matching unit-daemon feature prereleases.

Feature versions intentionally sort between the current stable and the next
stable. For example, `0.9.115-feature.1770000000` is newer than `0.9.114`, but
older than stable `0.9.115`.

## Board Layout

Daemon runtime config is per-user and is not stored under `/etc`:

```text
/home/txing/.config/txing/unit-daemon/.env
/home/txing/.config/txing/unit-daemon/AmazonRootCA1.pem
/home/txing/.config/txing/unit-daemon/certificate.arn
/home/txing/.config/txing/unit-daemon/certificate.pem.crt
/home/txing/.config/txing/unit-daemon/private.pem.key
/home/txing/.config/txing/unit-daemon/public.pem.key
```

The `.env` file is directly sourceable and contains host-independent runtime
values. Certificate paths are omitted by default; the daemon derives colocated
certificate paths from the loaded `.env` directory.

Stable mode uses the normal `txing` mise config tree and persistent install
tree:

```text
/home/txing/.config/mise/conf.d/txing-unit-daemon.toml
/home/txing/.local/share/mise/installs/txing-unit-daemon/
```

Feature mode is an overlay on top of stable. It uses an isolated mise config and
ephemeral install/cache/tmp state under executable `/var/tmp`:

```text
/home/txing/.config/mise/txing-unit-daemon/config.toml
/var/tmp/txing/unit-daemon/mise
/var/tmp/txing/unit-daemon/mise-cache
/var/tmp/txing/unit-daemon/mise-tmp
```

The feature systemd environment also sets:

```text
MISE_SHARED_INSTALL_DIRS=/home/txing/.local/share/mise/installs
```

That shared install directory is the fallback path to the persistent stable
daemon. Feature service start tries to install the latest feature-capable
resolution into `/var/tmp`; if that pre-start install fails or no newer feature
release is available, offline `mise exec` can still resolve the installed stable
daemon through the shared install directory.

The installed service is the same for both channels:

```text
/etc/systemd/system/txing-unit-daemon.service
```

The service waits for network-online and clock synchronization before start,
runs as the `txing` user, sends `SIGINT` on stop, and starts the daemon through:

```ini
ExecStart=/usr/bin/env MISE_OFFLINE=1 /home/txing/.local/bin/mise exec -- txing-unit-daemon
```

## Publishing

Stable publishing is CI-owned:

```text
.github/workflows/unit-daemon-stable-release.yml
```

The workflow runs manually from `main`, builds on `ubuntu-24.04-arm`, installs
Rust `1.95.0`, runs daemon tests, builds and strips the Linux `aarch64` binary,
packages the archive, and creates a normal GitHub Release for `v<VERSION>`.
Stable tags and releases are immutable.

Feature publishing is CI-owned:

```text
.github/workflows/unit-daemon-feature-prerelease.yml
```

The workflow runs manually from a pushed `feature/*` branch, builds on
`ubuntu-24.04-arm`, installs Rust `1.95.0`, runs daemon tests, builds and strips
the Linux `aarch64` binary, packages the archive, creates the timestamped
prerelease, and prunes older feature prereleases beyond the latest 10. The
workflow fails if it is dispatched from `main`, a tag, or any non-`feature/*`
branch.

## Integrity Policy

The current implemented integrity policy is:

- stable release tags and releases are immutable;
- feature prereleases are timestamped and retained only for recent testing;
- assets are retrieved from GitHub Releases over HTTPS through mise;
- feature mode disables SLSA and GitHub artifact attestation checks because
  checksum assets and attestations are not implemented for this channel.

Checksum assets or GitHub artifact attestations are not implemented yet. Add
them later only when stronger artifact integrity requirements are needed.

## Verified Behavior

The board install behavior has been manually verified on a Raspberry Pi Zero 2
W with a read-only root filesystem:

- feature service install into `/var/tmp` and read-only-root reboot;
- stable GitHub Actions release publish from `main`;
- stable board install from the `main` raw installer;
- stable upgrade with plain `mise upgrade`;
- stable read-only-root reboot on `0.9.114`, with systemd starting the daemon,
  MQTT connecting, and retained `board` online state publishing.

## Manual Actions

### Provision Local Daemon Config

Run this on macOS only when certificate or AWS daemon resource provisioning is
intended:

```bash
just unit::daemon::cert <thing-id>
```

The recipe writes `.env` and certificate material into:

```text
$HOME/.config/txing/unit-daemon
```

### Copy Daemon Config To The Board

From macOS:

```bash
test -r "$HOME/.config/txing/unit-daemon/.env"
test -r "$HOME/.config/txing/unit-daemon/private.pem.key"
COPYFILE_DISABLE=1 tar -C "$HOME/.config/txing" -czf /tmp/txing-unit-daemon-config.tgz unit-daemon
scp /tmp/txing-unit-daemon-config.tgz txing:/tmp/txing-unit-daemon-config.tgz
```

On the board as `txing`:

```bash
install -d -m 700 "$HOME/.config/txing"
tar -xzf /tmp/txing-unit-daemon-config.tgz -C "$HOME/.config/txing"
chmod 700 "$HOME/.config/txing/unit-daemon"
chmod 600 "$HOME/.config/txing/unit-daemon/.env"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.arn"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.pem.crt"
chmod 600 "$HOME/.config/txing/unit-daemon/private.pem.key"
chmod 600 "$HOME/.config/txing/unit-daemon/public.pem.key"
chmod 644 "$HOME/.config/txing/unit-daemon/AmazonRootCA1.pem"
rm -f /tmp/txing-unit-daemon-config.tgz
```

### Publish A Stable Release

Push the intended code to `main`, then run the `Unit Daemon Stable Release`
workflow manually from `main`. Enter the new stable version, or leave the input
blank to release the next minor version from the current root `VERSION`. The
workflow bumps managed version files, commits that release bump to `main`, and
publishes release `v<VERSION>`. It fails if that tag or release already exists.

### Install Stable On A Board

Run during a writable-root maintenance window:

```bash
root-rw
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh | sudo bash -s -- stable
```

Verify:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -n 120 --no-pager
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise list
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise which txing-unit-daemon
```

### Upgrade Stable On A Board

Run during a writable-root maintenance window:

```bash
root-rw
sudo apt update
sudo apt dist-upgrade -y
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise upgrade
sudo systemctl restart txing-unit-daemon.service
```

If a release was just published and mise still resolves the previous version:

```bash
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise cache clear
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise upgrade
sudo systemctl restart txing-unit-daemon.service
```

### Verify Stable Read-Only Reboot

```bash
root-ro
sudo reboot
```

After reconnecting:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -b -u txing-unit-daemon.service --no-pager
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise list
```

Expected: no source checkout is needed, the service starts offline, the daemon
logs the stable version, MQTT connects, and retained `board` online state is
published.

### Publish A Feature Prerelease

Push the feature branch, then run the `Unit Daemon Feature Prerelease` workflow
manually from that `feature/*` branch. The workflow file must already exist on
the default branch before GitHub exposes it for manual dispatch.

```bash
git push origin HEAD
```

The workflow publishes a timestamped prerelease tag for the selected branch
head and prunes older unit-daemon feature prereleases beyond the latest 10.

### Opt A Board Into Feature

Feature mode requires stable to be installed first. Run during a writable-root
maintenance window:

```bash
root-rw
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh | sudo bash -s -- feature
```

Feature service start may install a newer feature prerelease into `/var/tmp`.
If feature install is unavailable or no newer feature exists, the service uses
the persistent stable install through `MISE_SHARED_INSTALL_DIRS`.

### Opt A Board Out Of Feature

Run the stable installer again:

```bash
root-rw
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh | sudo bash -s -- stable
```

The stable installer removes the feature overlay config/state and restarts the
same `txing-unit-daemon.service` in stable mode.

### Check Raw GitHub Script Cache

Raw GitHub URLs can be cached briefly after a push. Check the fetched script
before executing it:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh \
  | grep -n 'MISE_SHARED_INSTALL_DIRS\|ExecStartPre=-.*mise install\|conf.d'
```

Use a commit-pinned raw URL if the board still sees an older script.
