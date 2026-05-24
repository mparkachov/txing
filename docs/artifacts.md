# Artifacts

This document describes release artifacts and channels. Host installation steps
live with the owning component:

- board install and maintenance: [Board](./components/board.md)
- rig install and deployment: [Rig](./components/rig.md)

## Release

Release artifacts are split by component. Each component has a committed
semantic version under `release/versions/`, and artifact-producing components
publish normal GitHub Releases with component-prefixed tags:

- rig: `release/versions/rig` publishes `rig-vX.Y.Z`
- Lambda: `release/versions/lambda` publishes `lambda-vX.Y.Z`
- unit: `release/versions/unit` publishes `unit-vX.Y.Z`
- office: `release/versions/office` tracks office version metadata only

Each manual release workflow is dispatched from the selected branch, reads only
its component version file, rejects an existing tag/release, and compares
monotonicity only within that component tag stream. Office has no GitHub
Release workflow or release asset; Cloudflare Pages builds and deploys office
from Git.

Rig releases publish these Linux `aarch64` assets:

```text
txing-sparkplug-manager-linux-aarch64.tar.gz
txing-ble-connectivity-linux-aarch64.tar.gz
```

Unit releases publish these Linux `aarch64` assets:

```text
txing-unit-daemon-linux-aarch64.tar.gz
txing-unit-kvs-master-linux-aarch64.tar.gz
txing-unit-hardware-worker-linux-aarch64.tar.gz
```

Lambda releases publish these Linux `aarch64` assets:

```text
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

1. Bump the intended component version locally.
2. Push the intended code to the branch that should be released.
3. Run the matching `Release rig`, `Release lambda`, or `Release unit` workflow
   manually from that branch.
4. Deploy AWS infrastructure and all standalone Lambda stacks with
   `just aws::deploy`.
5. Publish runtime Lambda code from the operator machine with
   `just aws::publish latest`. `latest` resolves within the `lambda-v*`
   release stream.
6. If a board or rig needs new binaries, update it manually from a root shell
   with writable root and root-owned `mise upgrade`; boards reboot, rigs
   restart `rig-daemon.target`.

Host `latest` resolution is component-specific: rig mise configs use
`version_prefix = "rig-v"` and board mise configs use
`version_prefix = "unit-v"`. This is forward-only operator state; manually
replace old host configs that do not include the prefix before relying on
`latest`.

## Lambda Artifacts

Production Lambda code is deployed from GitHub release assets by the operator
machine:

```bash
just aws::publish latest
```

`aws::publish` invokes the AWS-hosted publisher Lambda. `latest` resolves to the
newest `lambda-v*` component release, not the repository-wide latest release.
Explicit `lambda-vX.Y.Z` and bare `X.Y.Z` references select the Lambda stream;
exact legacy `vX.Y.Z` references remain available only for manual rollback to
old combined releases. The publisher downloads public GitHub release assets
over HTTPS, uploads Lambda artifacts, and updates existing Lambda functions.
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
txing-unit-kvs-master-linux-aarch64.tar.gz
txing-unit-hardware-worker-linux-aarch64.tar.gz
```

Installed commands:

```text
txing-unit-daemon
txing-unit-kvs-master
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
/root/.local/share/mise/installs/txing-unit-kvs-master/latest/txing-unit-kvs-master
/root/.local/share/mise/installs/txing-unit-hardware-worker/latest/txing-unit-hardware-worker
/root/.local/share/mise/installs/txing-unit-daemon/
/root/.local/share/mise/installs/txing-unit-kvs-master/
/root/.local/share/mise/installs/txing-unit-hardware-worker/
/etc/systemd/system/txing-unit.target
/etc/systemd/system/txing-unit-daemon.service
/etc/systemd/system/txing-unit-kvs-master.service
/etc/systemd/system/txing-unit-hardware-worker.service
```

The `daemon.env` file is a systemd-compatible environment file rendered from
`devices/unit/daemon/daemon.env.template`. It contains daemon-owned `TXING_*`
runtime defaults for video, capabilities, CloudWatch, hardware-worker socket
configuration, and motor control. The Go daemon consumes the daemon/cloud/video
keys. The hardware worker consumes the `TXING_HARDWARE_WORKER_*` and
`TXING_MOTOR_*` keys when its systemd unit loads the same root-owned env file.
Certificate paths are omitted by default; the daemon derives colocated
certificate paths from the loaded `daemon.env` directory.

The native KVS master is dynamically linked to the libcamera ABI from Raspberry
Pi OS Trixie packages. Release workflows assert that the asset links against
`libcamera.so.0.7` and `libcamera-base.so.0.7`; board maintenance instructions
run `ldd` on the installed `latest` binary before rebooting.

The `txing-unit.target` unit groups the daemon, KVS master, and hardware
worker services for boot. The board systemd units start the root-owned binaries
under mise's `latest` install paths. The daemon owns the local BoardVideoBridge
gRPC socket. The hardware worker owns the local UnitHardware gRPC socket. The
KVS master and daemon connect as separate services. All three services declare
`PartOf=txing-unit.target`, so stopping or restarting the target propagates to
the services. Restarts do not invoke mise or call GitHub. They do not depend on
generated shims. They do not use separate wrapper scripts.
Publishing a new GitHub Release does not upgrade a board automatically. Release
does not upgrade a board; the operator must log in to the board, switch to
root, run `root-rw`, run root-owned `mise upgrade`, verify versions, sync, and
reboot.
Boards that already ran the older board-named runtime need one manual cleanup
during that writable-root maintenance window: disable and remove
`txing-board.target` and `txing-board-kvs-master.service`, then run
`systemctl daemon-reload` before rebooting into `txing-unit.target`.

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
