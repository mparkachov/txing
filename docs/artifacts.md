# Artifacts

This document describes release artifacts and channels. Host installation steps
live with the owning component:

- board install and maintenance: [Board](./components/board.md)
- rig install and deployment: [Rig](./components/rig.md)

## Stable Release

`VERSION` is the stable repository version. Stable releases are normal GitHub
Releases:

- tag and release name: `v<VERSION>`
- publisher: manual `Txing Stable Release` GitHub Actions workflow from `main`
- GitHub prerelease flag: `false`
- release immutability: the workflow fails if `VERSION` is not newer than the
  latest existing stable `v*` tag, or if the tag/release already exists

Project stable releases publish these Linux `aarch64` assets:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
txing-sparkplug-manager-linux-aarch64.tar.gz
txing-ble-connectivity-linux-aarch64.tar.gz
txing-aws-connectivity-linux-aarch64.tar.gz
txing-rig-deploy-linux-aarch64.tar.gz
```

Each archive contains one root-level executable with the same command name.

Stable publishing flow:

1. Update all managed version files locally.
2. Push the intended code to `main`.
3. Run the `Txing Stable Release` workflow manually from `main`.
4. Deploy rig components from the operator machine with
   `just rig::deploy-release latest all`.
5. Update boards during writable-root maintenance by rerunning the board stable
   installer.

The workflow reads the pushed root `VERSION`, checks that all managed version
files already match, fails unless the version is newer than the latest existing
stable release, publishes the GitHub Release, and publishes the rig stable
binaries. It does not bump versions, commit, push back to `main`, build
Greengrass Lite, or deploy to hosts.

## Board Assets

Boards install these two release assets with root-owned `mise`:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
```

Installed commands:

```text
txing-unit-daemon
txing-board-kvs-master
```

The root-owned runtime layout is:

```text
/root/.config/txing/unit-daemon/daemon.env
/root/.config/txing/unit-daemon/AmazonRootCA1.pem
/root/.config/txing/unit-daemon/certificate.arn
/root/.config/txing/unit-daemon/certificate.pem.crt
/root/.config/txing/unit-daemon/private.pem.key
/root/.config/txing/unit-daemon/public.pem.key
/root/.config/mise/conf.d/txing-unit-daemon.toml
/root/.local/share/mise/installs/txing-unit-daemon/
/root/.local/share/mise/installs/txing-board-kvs-master/
/etc/systemd/system/txing-unit-daemon.service
```

The `daemon.env` file is sourceable and rendered from
`devices/unit/daemon/daemon.env.template`. It contains daemon-owned `TXING_*`
runtime defaults for video, capabilities, CloudWatch, and motor control.
Certificate paths are omitted by default; the daemon derives colocated
certificate paths from the loaded `daemon.env` directory.

The native KVS master is dynamically linked to the libcamera ABI from Raspberry
Pi OS Trixie packages. Release workflows assert that the asset links against
`libcamera.so.0.7` and `libcamera-base.so.0.7`; the board installer also runs
`ldd` on resolved binaries before restarting systemd.

Board feature mode is an overlay on top of stable. It resolves GitHub
prereleases with `mise`, installs selected feature binaries into the same
persistent root-owned mise install tree, and uses `/var/tmp` only for cache/tmp
scratch. Service starts are offline; rerun the feature or stable installer to
change installed versions.

## Unit Daemon Feature Prerelease

Feature releases are GitHub prereleases for board daemon/KVS iteration:

- tag and release name: `v<NEXT_PATCH>-feature.<unix_timestamp>`
- version source: next patch after root `VERSION`, plus a Unix timestamp
- publisher: manual `Unit Daemon Feature Prerelease` GitHub Actions workflow
  from a pushed `feature/*` branch
- GitHub prerelease flag: `true`
- retention: latest 10 matching unit-daemon feature prereleases

Feature versions intentionally sort between the current stable and the next
stable. For example, `0.9.115-feature.1770000000` is newer than `0.9.114`, but
older than stable `0.9.115`.

The feature workflow publishes:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
```

Boards opt into feature by running the board installer with `feature`; see the
[Board maintenance section](./components/board.md#maintenance).

## Rig Stable Artifacts

Stable rig hosts receive txing binaries through Greengrass cloud deployments.
The rig does not need a source checkout, `mise`, AWS CLI, AWS access keys, or
local Rust/CMake compilation for the stable runtime path.

`just rig::deploy-release` runs on the operator Mac, applies the repository AWS
profile/credentials, downloads stable GitHub release assets with `gh`, uploads
Linux component binaries to the Greengrass artifacts bucket, creates Greengrass
component versions from the stable project SemVer, and creates continuous
deployments for the rig-type thing groups. The Linux component binaries are not
executed on the operator Mac.

Greengrass Lite is installed from the official upstream AWS release, not from a
txing release asset:

```text
https://github.com/aws-greengrass/aws-greengrass-lite/releases
aws-greengrass-lite-deb-arm64.zip
```

The stable release workflow does not build, package, or publish Greengrass
Lite. The checked-in Greengrass Lite submodule remains for source-checkout
development and local debugging only.

## Integrity Policy

The implemented integrity policy is:

- stable release tags and releases are immutable
- feature prereleases are timestamped and retained only for recent testing
- assets are retrieved from GitHub Releases over HTTPS through `mise` or `gh`
- feature mode disables SLSA and GitHub artifact attestation checks because
  checksum assets and attestations are not implemented for that channel

Checksum assets or GitHub artifact attestations are not implemented yet. Add
them later only when stronger artifact integrity requirements are needed.

## Verified Behavior

The current release flow has been manually verified on Raspberry Pi Zero 2 W
boards and Greengrass rigs:

- feature board install into `/root/.local/share/mise/installs`
- stable board install from the `main` raw installer
- stable board upgrade with the root-owned installer
- read-only-root board reboot with systemd starting the daemon offline
- REDCON `4` to `1` convergence
- browser AWS KVS video
- browser MCP motor control over WebRTC data channel at REDCON `1`
- MQTT MCP fallback at REDCON `2`
- rig stable component publish from GitHub release assets through
  `just rig::deploy-release`
