# Artifacts

This document describes release artifacts and channels. Host installation steps
live with the owning component:

- board install and maintenance: [Board](./components/board.md)
- rig install and deployment: [Rig](./components/rig.md)

## Release

`VERSION` is the repository release version. Releases are normal GitHub
Releases:

- tag and release name: `v<VERSION>`
- publisher: manual `Txing Release` GitHub Actions workflow from the selected branch
- release immutability: the workflow fails if `VERSION` is not newer than the
  latest existing `v*` tag, or if the tag/release already exists
- release retention: after publishing, the workflow keeps the newest 10 project
  releases matching `vX.Y.Z` and deletes older releases with their tags

Project releases publish these Linux `aarch64` assets:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
txing-unit-hardware-worker-linux-aarch64.tar.gz
txing-sparkplug-manager-linux-aarch64.tar.gz
txing-ble-connectivity-linux-aarch64.tar.gz
txing-witness-lambda-linux-aarch64.zip
txing-cloud-rig-lambda-linux-aarch64.zip
txing-cloud-mcu-lambda-linux-aarch64.zip
```

Each `.tar.gz` archive contains one root-level executable with the same command
name. Each runtime Lambda `.zip` contains one root-level Go executable named
`bootstrap` for the `provided.al2023` arm64 runtime. Lambda release artifacts
are built as `linux/arm64` binaries with `CGO_ENABLED=0`, so they are static
and do not depend on host glibc.

Release publishing flow:

1. Update all managed version files locally.
2. Push the intended code to the branch that should be released.
3. Run the `Txing Release` workflow manually from that branch.
4. Deploy AWS infrastructure and all standalone Lambda stacks with
   `just aws::deploy`.
5. Publish runtime Lambda code from the operator machine with
   `just aws::publish latest`.
6. If a board or rig needs new binaries, update it manually from a root shell
   with writable root and root-owned `mise upgrade`; boards reboot, rigs
   restart `rig-daemon.target`.

The workflow reads the selected branch's root `VERSION`, checks that all managed version
files already match, fails unless the version is newer than the latest existing
release, publishes the GitHub Release, and publishes the board, rig, and Lambda
artifacts. After a successful publish, it prunes older project releases down to
the newest 10. It does not bump versions, commit, push back to a branch, upload
Lambda code to AWS, or deploy to hosts.

## Lambda Artifacts

Production Lambda code is deployed from GitHub release assets by the operator
machine:

```bash
just aws::publish latest
```

`aws::publish` invokes the AWS-hosted publisher Lambda. The publisher downloads
public GitHub release assets over HTTPS, uploads Lambda artifacts, and updates
existing Lambda functions.
Runtime Lambda deploy recipes seed placeholder bootstrap zips so first-time
stack creation does not depend on release artifacts already being uploaded.
`aws::publish-lambda` runs the same runtime Lambda publish code locally and is
kept for manual repair or one-off publishing before the publisher Lambda exists.
Admin Lambda deploy recipes package the current Python source into each
standalone admin Lambda stack.

## Board Assets

Boards install these three release assets with root-owned `mise`:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-board-kvs-master-linux-aarch64.tar.gz
txing-unit-hardware-worker-linux-aarch64.tar.gz
```

Installed commands:

```text
txing-unit-daemon
txing-board-kvs-master
txing-unit-hardware-worker
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
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon
/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker
/root/.local/share/mise/installs/txing-unit-daemon/
/root/.local/share/mise/installs/txing-board-kvs-master/
/root/.local/share/mise/installs/txing-unit-hardware-worker/
/etc/systemd/system/txing-board.target
/etc/systemd/system/txing-unit-daemon.service
/etc/systemd/system/txing-board-kvs-master.service
/etc/systemd/system/txing-unit-hardware-worker.service
```

The `daemon.env` file is sourceable and rendered from
`devices/unit/daemon/daemon.env.template`. It contains daemon-owned `TXING_*`
runtime defaults for video, capabilities, CloudWatch, hardware-worker socket
configuration, and motor control. The daemon consumes the daemon/cloud/video
keys. The hardware worker consumes the `TXING_HARDWARE_WORKER_*` and
`TXING_MOTOR_*` keys when its systemd unit loads the same root-owned env file.
Certificate paths are omitted by default; the daemon derives colocated
certificate paths from the loaded `daemon.env` directory.

The native KVS master is dynamically linked to the libcamera ABI from Raspberry
Pi OS Trixie packages. Release workflows assert that the asset links against
`libcamera.so.0.7` and `libcamera-base.so.0.7`; board maintenance instructions
run `ldd` on the installed `latest` binary before rebooting.

The `txing-board.target` unit groups the daemon, KVS master, and hardware
worker services for boot. The board systemd units start the root-owned binaries
under mise's `latest` install paths. The daemon owns the local BoardVideoBridge
gRPC socket. The hardware worker owns the local UnitHardware gRPC socket. The
KVS master and daemon connect as separate services. All three services declare
`PartOf=txing-board.target`, so stopping or restarting the target propagates to
the services. Restarts do not invoke mise or call GitHub. They do not depend on
generated shims. They do not use separate wrapper scripts.
Publishing a new GitHub Release does not upgrade a board automatically. Release
does not upgrade a board; the operator must log in to the board, switch to
root, run `root-rw`, run root-owned `mise upgrade`, verify versions, sync, and
reboot.

## Rig Artifacts

Production `raspi` rig hosts install txing binaries through root-owned `mise`
from GitHub Releases. The rig host does not need a source checkout, AWS CLI, AWS
access keys, or local compilation for the release runtime path.

Production `cloud` rig code is shipped as Lambda release artifacts:
`txing-cloud-rig-lambda-linux-aarch64.zip` and
`txing-cloud-mcu-lambda-linux-aarch64.zip`.

Rig assets:

```text
txing-sparkplug-manager-linux-aarch64.tar.gz
txing-ble-connectivity-linux-aarch64.tar.gz
```

Installed commands:

```text
txing-sparkplug-manager
txing-ble-connectivity
```

Rigs use root's persistent mise config and install tree:

```text
/root/.config/txing/rig-daemon/daemon.env
/root/.config/mise/conf.d/txing-rig.toml
/root/.local/share/mise/installs/txing-sparkplug-manager/latest/txing-sparkplug-manager
/root/.local/share/mise/installs/txing-ble-connectivity/latest/txing-ble-connectivity
/etc/systemd/system/txing-sparkplug-manager.service
/etc/systemd/system/txing-ble-connectivity.service
/etc/systemd/system/rig-daemon.target
```

Publishing a new GitHub Release does not upgrade a rig; the operator must log
in to the rig, switch to root, run root-owned `mise upgrade`, verify versions,
sync, and restart `rig-daemon.target`.

## Integrity Policy

The implemented integrity policy is:

- release tags and releases are immutable
- assets are retrieved from GitHub Releases over HTTPS through `mise` or the
  Python publisher

Checksum assets or GitHub artifact attestations are not implemented yet. Add
them later only when stronger artifact integrity requirements are needed.

## Verified Behavior

The current release flow has been manually verified on Raspberry Pi Zero 2 W
boards and standalone rig daemons:

- board install into `/root/.local/share/mise/installs`
- board manual upgrade with root-owned `mise upgrade`
- read-only-root board reboot with systemd starting the daemon offline
- REDCON `4` to `1` convergence
- browser AWS KVS video
- browser MCP motor control over WebRTC data channel at REDCON `1`
- MQTT MCP fallback at REDCON `2`
- rig daemon install and upgrade from GitHub release assets through root-owned
  `mise`
