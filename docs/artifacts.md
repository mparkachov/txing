# Artifacts

This document describes the implemented artifact flow for installing the `unit`
daemon and native KVS master on Raspberry Pi boards without keeping a source
checkout on the board. The board uses `mise` to install GitHub Release assets
and `systemd` to run the daemon.

## Unit Daemon Channels

The board has two installed commands:

```text
txing-unit-daemon
txing-board-kvs-master
```

Both stable and feature releases publish the same board assets:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
```

Each archive contains one root-level executable with the matching command name:

```text
txing-unit-daemon
txing-board-kvs-master
```

Stable releases are normal GitHub Releases:

- tag and release name: `v<VERSION>`, for example `v0.9.114`;
- version source: the pushed repository root `VERSION`;
- publisher: manual `Txing Stable Release` GitHub Actions workflow from `main`;
- GitHub prerelease flag: `false`;
- release immutability: the workflow fails if `VERSION` is not newer than the
  latest existing stable `v*` tag, or if the stable tag/release already exists.

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

## Rig Stable Artifacts

Stable rig hosts receive txing binaries through Greengrass cloud deployments.
The rig does not need a source checkout, mise, AWS CLI, AWS access keys, or
local Rust/CMake compilation for the stable runtime path.

Project stable releases publish these project-versioned assets on `v<VERSION>`:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
txing-sparkplug-manager-linux-aarch64.tar.gz
txing-ble-connectivity-linux-aarch64.tar.gz
txing-aws-connectivity-linux-aarch64.tar.gz
txing-rig-deploy-linux-aarch64.tar.gz
```

Each archive contains one root-level executable with the same command name.
`just rig::deploy-release` runs on the operator Mac, applies the repository AWS
profile/credentials, downloads these assets with `gh`, and uses the release's
`txing-rig-deploy` shell script to upload component binaries to the existing
Greengrass artifacts bucket, create Greengrass component versions, and create
the rig-type deployments. The Linux component binaries are not executed on the
operator Mac.

Greengrass Lite is installed from the official upstream AWS release, not from a
txing release asset:

```text
https://github.com/aws-greengrass/aws-greengrass-lite/releases
aws-greengrass-lite-deb-arm64.zip
```

The stable release workflow does not build, package, or publish Greengrass Lite.
The checked-in Greengrass Lite submodule remains for source-checkout development
and local debugging only. Stable rigs install the upstream Debian package from a
root shell and then receive txing components through Greengrass cloud
deployments.

The canonical stable rig installation and deployment flow is documented in
[Rig](./components/rig.md).

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
/home/txing/.local/share/mise/installs/txing-board-kvs-master/
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
daemon and native KVS master. Feature service start tries to upgrade the
feature-capable resolution in `/var/tmp` before ensuring it is installed; if
those pre-start steps fail or no feature release is installed, offline
`mise exec` can still resolve the installed stable tools through the shared
install directory.

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
Rust `1.95.0`, runs Rust tests, builds the native KVS master, builds and strips
the Linux `aarch64` binaries, packages the project stable assets, and creates a
normal GitHub Release for `v<VERSION>`. Stable project tags and releases are
immutable.

Feature publishing is CI-owned:

```text
.github/workflows/unit-daemon-feature-prerelease.yml
```

The workflow runs manually from a pushed `feature/*` branch, builds on
`ubuntu-24.04-arm`, installs Rust `1.95.0`, runs daemon tests, builds the
native KVS master, builds and strips the Linux `aarch64` binaries, packages the
archives, creates the timestamped prerelease, and prunes older feature
prereleases beyond the latest 10. The workflow fails if it is dispatched from
`main`, a tag, or any non-`feature/*` branch.

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

- feature service generation with `/var/tmp` runtime state and read-only-root reboot;
- stable GitHub Actions release publish from `main`;
- stable board generation from the `main` raw script plus manual systemd install;
- stable upgrade with plain `mise upgrade`;
- stable read-only-root reboot on `0.9.114`, with systemd starting the daemon,
  MQTT connecting, and retained `board` online state publishing.

The current phase-2a artifact flow installs both `txing-unit-daemon` and
`txing-board-kvs-master` through the same board mise config. It still needs
field validation on a clean board after the next stable release is published.

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

### Refresh Existing Daemon Role Policy

New certificate provisioning writes the current daemon role policy. Existing
devices that were provisioned before the native KVS master role permissions
must be refreshed from the operator machine:

```bash
just unit::daemon::role-policy <thing-id>
```

The recipe updates only the per-device daemon IAM role inline policy. It does
not issue a new certificate.

### Publish A Stable Release

Update all managed version files locally, push the intended code to `main`, then
run the `Txing Stable Release` workflow manually from `main`. The workflow reads
the pushed root `VERSION`, checks that all managed version files already match,
fails unless that version is newer than the latest existing stable `v*` tag, and
publishes release `v<VERSION>`. It does not bump versions, commit, push back to
`main`, build Greengrass Lite, or publish Greengrass Lite.

### Install Stable On A Rig

This is the fresh-host stable path. The rig must already have the AWS stack,
town thing, rig thing, and rig certificate material prepared.

After installing the upstream Greengrass Lite Debian package, publish the stable
GitHub release artifacts from the operator Mac:

```bash
just rig::deploy-release latest all
```

Greengrass Lite host configuration is a manual privileged step. Repository
scripts do not copy files into system locations, create users, write
Greengrass configuration, or start systemd units.
Use `ggcore` for Greengrass Lite core services and `gg_component` for normal
Greengrass components. Raspi rigs should add `gg_component` to the OS
`bluetooth` group so BLE access uses BlueZ/D-Bus without a privileged
component lifecycle.

Normal stable update:

```bash
just rig::deploy-release latest all
```

### Remove An Old Rig Install Manually

The stable rig tooling is fresh-host only. It does not migrate or clean up old
installations automatically. Before using the new path on an older rig, remove
the old Greengrass Lite target, txing component services, `/etc/greengrass`,
`/var/lib/greengrass`, `/run/greengrass`, and the old txing tmpfiles entry as a
manual privileged host-maintenance step.

### Install Stable On A Board

Run during a writable-root maintenance window:

```bash
root-rw
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh -o /tmp/txing-install-systemd.sh
sudo -u txing env HOME=/home/txing bash /tmp/txing-install-systemd.sh stable
sudo install -m 644 /home/txing/.config/txing/unit-daemon/systemd/txing-unit-daemon.service /etc/systemd/system/txing-unit-daemon.service
sudo systemctl disable --now txing-unit-daemon-feature.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/txing-unit-daemon-feature.service
if systemctl list-unit-files NetworkManager-wait-online.service --no-legend --no-pager 2>/dev/null | grep -q '^NetworkManager-wait-online\.service[[:space:]]'; then
  sudo systemctl enable NetworkManager-wait-online.service
fi
sudo systemctl daemon-reload
sudo systemctl enable --now txing-unit-daemon.service
```

Verify:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -n 120 --no-pager
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise list
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise which txing-unit-daemon
sudo -u txing env HOME=/home/txing /home/txing/.local/bin/mise which txing-board-kvs-master
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
logs the stable version, MQTT connects, the native KVS master resolves through
mise, and retained `board`, `mcp`, and `video` state is published.

### Publish A Feature Prerelease

Use this path for Phase 2a board iteration before publishing a stable project
release. Push the feature branch, then run the `Unit Daemon Feature Prerelease`
workflow manually from that `feature/*` branch. The workflow file must already
exist on the default branch before GitHub exposes it for manual dispatch.

```bash
git push origin HEAD
```

The workflow publishes a timestamped prerelease tag for the selected branch head
with both board assets:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
```

It also prunes older unit-daemon feature prereleases beyond the latest 10.

### Opt A Board Into Feature

Feature mode requires stable to be installed first. Run during a writable-root
maintenance window:

```bash
root-rw
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh -o /tmp/txing-install-systemd.sh
sudo -u txing env HOME=/home/txing bash /tmp/txing-install-systemd.sh feature
sudo install -m 644 /home/txing/.config/txing/unit-daemon/systemd/txing-unit-daemon.service /etc/systemd/system/txing-unit-daemon.service
sudo systemctl daemon-reload
sudo systemctl restart txing-unit-daemon.service
```

While validating generator changes that are still only on a feature branch, use
the generator from that same branch instead of `main`:

```bash
FEATURE_BRANCH=feature/phase-2a-kvs
curl -fsSL "https://raw.githubusercontent.com/mparkachov/txing/${FEATURE_BRANCH}/devices/unit/daemon/install-systemd.sh" -o /tmp/txing-install-systemd.sh
sudo -u txing env HOME=/home/txing bash /tmp/txing-install-systemd.sh feature
sudo install -m 644 /home/txing/.config/txing/unit-daemon/systemd/txing-unit-daemon.service /etc/systemd/system/txing-unit-daemon.service
sudo systemctl daemon-reload
sudo systemctl restart txing-unit-daemon.service
```

Feature service start may install a newer feature prerelease into `/var/tmp`.
If feature install is unavailable or no newer feature exists, the service uses
the persistent stable install through `MISE_SHARED_INSTALL_DIRS`.

Verify the feature service resolves both commands:

```bash
sudo -u txing env HOME=/home/txing MISE_CONFIG_DIR=/home/txing/.config/mise/txing-unit-daemon \
  MISE_DATA_DIR=/var/tmp/txing/unit-daemon/mise \
  MISE_CACHE_DIR=/var/tmp/txing/unit-daemon/mise-cache \
  MISE_TMP_DIR=/var/tmp/txing/unit-daemon/mise-tmp \
  MISE_SHARED_INSTALL_DIRS=/home/txing/.local/share/mise/installs \
  /home/txing/.local/bin/mise which txing-unit-daemon
sudo -u txing env HOME=/home/txing MISE_CONFIG_DIR=/home/txing/.config/mise/txing-unit-daemon \
  MISE_DATA_DIR=/var/tmp/txing/unit-daemon/mise \
  MISE_CACHE_DIR=/var/tmp/txing/unit-daemon/mise-cache \
  MISE_TMP_DIR=/var/tmp/txing/unit-daemon/mise-tmp \
  MISE_SHARED_INSTALL_DIRS=/home/txing/.local/share/mise/installs \
  /home/txing/.local/bin/mise which txing-board-kvs-master
```

### Opt A Board Out Of Feature

Run the stable generator again and reinstall the generated unit:

```bash
root-rw
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh -o /tmp/txing-install-systemd.sh
sudo -u txing env HOME=/home/txing bash /tmp/txing-install-systemd.sh stable
sudo install -m 644 /home/txing/.config/txing/unit-daemon/systemd/txing-unit-daemon.service /etc/systemd/system/txing-unit-daemon.service
sudo systemctl daemon-reload
sudo systemctl restart txing-unit-daemon.service
```

The stable generator removes the feature overlay config. The manual systemd
restart switches the same `txing-unit-daemon.service` back to stable mode.

### Check Raw GitHub Script Cache

Raw GitHub URLs can be cached briefly after a push. Check the fetched script
before executing it:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh \
  | grep -n 'MISE_SHARED_INSTALL_DIRS\|ExecStartPre=-.*mise upgrade\|ExecStartPre=-.*mise install\|conf.d'
```

Use a commit-pinned raw URL if the board still sees an older script.
