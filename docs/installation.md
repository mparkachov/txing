# Installation

This page is the host setup index. Detailed runtime setup lives with the
component that owns the host behavior.

## Shared Assumptions

- Development machines may use a repository checkout.
- Production board hosts install release artifacts with `mise` and do not need a
  source checkout for the release runtime path.
- Production `raspi` rig hosts install standalone txing daemon release
  artifacts with root-owned `mise` and systemd.
- Production `cloud` rigs are AWS-hosted Lambda/EventBridge/SQS runtimes and
  do not have a host install path.
- Operator AWS account, credentials, profile selection, and region come from
  native AWS CLI configuration.
- Stack-backed operator commands and deploys fail unless `TXING_AWS_STACK` is
  set explicitly in the operator environment or passed as a positional stack
  prefix where supported. The base CloudFormation stack is derived as
  `<TXING_AWS_STACK>-aws-base`.
- The one-off `just aws::deploy-init` step stores office/admin deploy parameters
  from `shared/aws/deploy-init.json` as separate `/txing/stack/*` SSM Parameter
  Store values before the first base stack deployment. These three manual input
  parameters intentionally remain after `just aws::delete`; use
  `just aws::delete-init` only when you want to remove them too.

## Development Machine

Ubuntu LTS is the default development environment. Install Ubuntu-packaged
system and native-build tools with APT, then use Mise for developer and Codex
tools: Codex CLI, Ripgrep, AWS CLI v2, GitHub CLI, `jq`, Node.js, Bun, `just`,
and `uv`. Go is installed from Ubuntu as `golang-go`. The canonical package
lists, Mise bootstrap, and
component-specific native build dependencies are in
[Base Tooling](./development.md#base-tooling).

After that setup, confirm the shared commands resolve:

```bash
aws --version
codex --version
gh --version
go version
git --version
protoc --version
rg --version
just --version
uv --version
bun --version
node --version
nerdctl --version
```

The AWS CLI version must be v2. Board Alpine builds and cross-distro smoke
tests require a locally installed `nerdctl` connected to a native Linux/arm64
containerd environment; no Docker group membership is required.

Day-to-day development commands live in [development.md](./development.md).
AWS bring-up and teardown live in [aws.md](./aws.md).

## Raspi Rig Host

The `raspi` rig is the always-on host coordinator that owns Sparkplug
publication for local BLE and Thread-managed devices. Production `raspi` rig
hosts run `txing-sparkplug-manager`, `txing-thread-connectivity`, and
`txing-ble-connectivity` as standalone systemd services. `daemon.env` controls
which services are expected to run; the generated default enables only
`txing-sparkplug-manager`.

Canonical `raspi` rig installation, Bluetooth setup, root-owned `mise`,
systemd units, health-check, and update instructions live in
[components/rig.md](./components/rig.md).

`power-si` Thread devices also require an already configured external OTBR on
the rig network. OTBR installation is intentionally not automated by txing; the
operator must prepare OTBR, provision the device factory dataset, and flash the
XIAO MG24 manually as documented in
[Power SI Device](../devices/power-si/README.md).

The short production flow is:

1. Install host packages, Bluetooth, and root-owned `mise` on the rig.
2. Generate the rig daemon environment/certificate bundle on the operator
   machine with
   `just aws::cert <rig-id>`.
3. Copy and unpack `<rig-id>-rig-daemon-config.tgz` under
   `/root/.config/txing/rig-daemon`.
4. Install `txing-sparkplug-manager`, `txing-thread-connectivity`, and
   `txing-ble-connectivity` through root-owned `mise`.
5. Create `txing-sparkplug-manager.service`,
   `txing-thread-connectivity.service`, `txing-ble-connectivity.service`, and
   `rig-daemon.target` manually.
6. Start or upgrade with `sudo systemctl restart rig-daemon.target` after
   `mise upgrade`.
7. For `power-si`, verify OTBR readiness and SRP/DNS-SD discovery separately
   before expecting `txing-thread-connectivity` to publish Thread state.

## Cloud Rig Runtime

The `cloud` rig type is AWS-hosted. Deploy its Lambda/EventBridge/SQS
infrastructure through CloudFormation, then publish runtime Lambda release
artifacts:

```bash
just aws::deploy
just release::publish lambda
```

Cloud MCU registration and runtime behavior are documented in
[Cloud MCU](../devices/cloud-mcu/README.md).

## Board Host

The board is the device-side Raspberry Pi. Production boards run the root-owned
Go `txing-unit-daemon`, shared native `txing-board-kvs-master`, and native
`txing-unit-hardware-worker` installed from GitHub Release assets through
`mise`. Release binaries are built in the pinned Alpine musl container under
the shared board contract: the daemon and hardware worker are fully static and
run on both Raspberry Pi OS (Debian) and Alpine boards, while the KVS master
is musl-dynamic against Alpine libcamera and runs on Alpine boards only —
existing Debian boards stay pinned to the last Debian-built KVS master until
reimaged to Alpine.

Canonical board installation, runtime config, root-owned service setup,
read-only-root layout, manual maintenance, and validation instructions live in
[components/board.md](./components/board.md).

The short production flow is:

1. Write the Alpine `v3.24` aarch64 Raspberry Pi image with Raspberry Pi
   Imager and boot the diskless system.
2. Enter a root shell and use the board `unattended.sh` flow to create the
   persistent Alpine sys install.
3. Confirm the scripted runtime package baseline and root-owned `mise` install.
4. Generate the daemon environment/certificate bundle on the operator machine
   with
   `just aws::cert <thing-id>`.
5. Copy and unpack `<thing-id>-daemon-config.tgz` under
   `/root/.config/txing/unit-daemon`, including `daemon.env` and certificate
   files plus the complete board OpenRC service catalog.
6. Install the root-owned mise release tools, copy the Unit daemon and hardware
   worker scripts plus the common KVS script from the bundle's `services/`
   directory into `/etc/init.d`, and enable them with `rc-update` as documented
   in the board guide.
7. Configure the PWM overlay and read-only-root tmpfs layout.
8. Reboot and verify all three board services, KVS readiness, hardware-worker
   readiness, and REDCON convergence.

## Cyberbrick Board Host

The cyberbrick board is a supported device-side Raspberry Pi board running
Alpine Linux aarch64. Production Cyberbrick boards run the root-owned Go
`txing-cyberbrick-daemon`, shared native `txing-board-kvs-master`, static
`txing-cyberbrick-mavlink`, and static `txing-cyberbrick-ardupilot` from
the `cyberbrick-v*` and `kvs-master-v*` GitHub Release streams through root-owned `mise`,
supervised by OpenRC on a read-only root filesystem. ArduPilot is the PWM
owner and receives its tracked defaults on every tmpfs-backed boot. The daemon
and MAVLink service are fully static musl binaries; the KVS master is
dynamically linked against musl and Alpine libcamera, so the installed Alpine
`v3.24` packages and release stream move together for the camera. Cyberbrick
does not install or start a hardware worker.

Canonical cyberbrick board installation, Alpine sys install, OpenRC service
setup, read-only-root layout, manual maintenance, and validation instructions
live in
[components/board.md](./components/board.md).

The short production flow is:

1. Write the Alpine `v3.24` aarch64 Raspberry Pi image, run `setup-alpine`,
   and convert the card to a persistent install with `setup-disk -m sys`.
2. Install the runtime apk packages and root-owned `mise`.
3. Provision the MAVLink KVS resource and IAM policy with `just aws::deploy`,
   then generate the daemon environment/certificate bundle on the operator
   machine with `just aws::cert <thing-id>`.
4. Copy and unpack `<thing-id>-daemon-config.tgz` under
   `/root/.config/txing/cyberbrick-daemon`, including `daemon.env` and
   certificate files plus the complete board OpenRC service catalog.
5. In one writable-root window, install the three Cyberbrick artifacts plus the
   shared KVS artifact, copy the packaged Cyberbrick scripts plus the common KVS script as
   `txing-cyberbrick-ardupilot`, `txing-cyberbrick-mavlink`,
   `txing-cyberbrick-daemon`, and `txing-cyberbrick-kvs-master` OpenRC
   scripts into `/etc/init.d`, and enable them with
   `rc-update add <service> default`.
6. Verify ArduPilot binds only `127.0.0.1:14550`, the four-service dependency
   order, the packaged defaults, and hardware-worker removal.
7. Configure the PWM overlay and the read-only-root fstab/tmpfs layout.
8. Reboot with read-only root, repeat the service/default/local-UDP checks,
   deploy Office, then manually remove obsolete MCP shadow and retained-topic
   state. The full runtime commands are in
   [Cyberbrick runtime](./components/board.md#cyberbrick-runtime).

## Web

The operator/admin SPA is documented in [components/office.md](./components/office.md).

Local development:

```bash
just office::install
just office::write-env
just office::dev
```

Production office publishing is handled by Cloudflare Pages from the `office`
directory.

## Public Site

The public site is documented in [components/www.md](./components/www.md).

Local development:

```bash
cd www
python3 -m http.server 5174
```
