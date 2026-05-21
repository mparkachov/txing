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
txing-sparkplug-manager-linux-aarch64.tar.gz
txing-ble-connectivity-linux-aarch64.tar.gz
txing-aws-connectivity-linux-aarch64.tar.gz
txing-rig-deploy-linux-aarch64.tar.gz
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
4. For a brand-new stack only, seed Lambda bootstrap artifacts with
   `just aws::publish-lambda latest`.
5. Apply AWS infrastructure changes with `just aws::deploy`.
6. Publish Lambda code and Greengrass components from the operator machine with
   `just aws::publish latest`.
7. If a board needs the new binaries, update it manually from a board root
   shell with writable root, root-owned `mise upgrade`, and a reboot.

The workflow reads the selected branch's root `VERSION`, checks that all managed version
files already match, fails unless the version is newer than the latest existing
release, publishes the GitHub Release, and publishes the board, rig, and Lambda
artifacts. After a successful publish, it prunes older project releases down to
the newest 10. It does not bump versions, commit, push back to a branch, build
Greengrass Lite, upload Lambda code to AWS, or deploy to hosts.

## Lambda Artifacts

Production Lambda code is deployed from GitHub release assets by the operator
machine:

```bash
just aws::publish latest
```

`aws::publish` invokes the AWS-hosted publisher Lambda. The publisher downloads
public GitHub release assets over HTTPS, uploads Lambda and Greengrass artifacts,
updates existing Lambda functions, creates Greengrass component versions, and
creates both `raspi` and `cloud` Greengrass deployments.
`aws::publish-lambda` runs the same Lambda publish code locally and is kept for
first-time stack creation before the publisher Lambda exists.
`just aws::deploy` applies CloudFormation and publishes Python admin Lambda
source used by `aws-publish-release`, `aws-enlist-txing`, and `aws-clean-stack`.

For local Lambda iteration from macOS or Linux, use:

```bash
just aws::deploy-local-lambda txing-witness-lambda
```

The argument can be `all`, `witness`, `cloud-rig`, `cloud-mcu`, or the full
runtime Lambda function name. This builds local `linux/arm64` `bootstrap` zips,
replaces the stable `lambda/<function>/current/bootstrap.zip` object in S3, and
updates existing runtime Lambda functions from that S3 object. It does not
create a GitHub release or immutable versioned release artifact.

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
/root/.local/share/mise/installs/txing-unit-daemon/latest/txing-unit-daemon
/root/.local/share/mise/installs/txing-board-kvs-master/latest/txing-board-kvs-master
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
`libcamera.so.0.7` and `libcamera-base.so.0.7`; board maintenance instructions
run `ldd` on the installed `latest` binary before rebooting.

The board systemd unit starts the root-owned binaries under mise's `latest`
install paths. Service restarts do not invoke mise, call GitHub, depend on
generated shims, or use separate wrapper scripts. Publishing a new GitHub
Release does not upgrade a board; the operator must log in to the board, switch
to root, run `root-rw`, run root-owned `mise upgrade`, verify versions, sync,
and reboot.

## Rig Artifacts

Production `raspi` rig hosts receive txing binaries through Greengrass cloud
deployments. The rig host does not need a source checkout, `mise`, AWS CLI, AWS
access keys, or local Rust/CMake compilation for the release runtime path.

Production `cloud` rig code is shipped as Lambda release artifacts:
`txing-cloud-rig-lambda-linux-aarch64.zip` and
`txing-cloud-mcu-lambda-linux-aarch64.zip`.

`just aws::publish-rig latest` runs the same Greengrass publish code locally as
a fallback. It uses the operator AWS credentials, downloads public GitHub
release assets over HTTPS, uploads Linux component binaries to the Greengrass
artifacts bucket, creates Greengrass component versions from the project SemVer,
and creates continuous deployments for both `raspi` and `cloud` rig-type thing
groups. The Linux component binaries are not executed on the operator Mac.

Greengrass Lite is installed from the official upstream AWS release, not from a
txing release asset:

```text
https://github.com/aws-greengrass/aws-greengrass-lite/releases
aws-greengrass-lite-deb-arm64.zip
```

The release workflow does not build, package, or publish Greengrass Lite. The
repository no longer keeps a Greengrass Lite source checkout; install and
upgrade the upstream distribution package manually on rig hosts.

## Integrity Policy

The implemented integrity policy is:

- release tags and releases are immutable
- assets are retrieved from GitHub Releases over HTTPS through `mise` or the
  Python publisher

Checksum assets or GitHub artifact attestations are not implemented yet. Add
them later only when stronger artifact integrity requirements are needed.

## Verified Behavior

The current release flow has been manually verified on Raspberry Pi Zero 2 W
boards and Greengrass rigs:

- board install into `/root/.local/share/mise/installs`
- board manual upgrade with root-owned `mise upgrade`
- read-only-root board reboot with systemd starting the daemon offline
- REDCON `4` to `1` convergence
- browser AWS KVS video
- browser MCP motor control over WebRTC data channel at REDCON `1`
- MQTT MCP fallback at REDCON `2`
- rig component publish from GitHub release assets through
  `just aws::publish-rig`
