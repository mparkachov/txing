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

Repo-wide developer tooling:

- `uv`
- `just`
- `jq`
- AWS CLI v2
- GitHub CLI (`gh`) for dispatching release workflows

Install operator CLIs with the package manager you use for the development
machine. `mise` is acceptable for missing or stale CLI versions:

```bash
mise use --global uv@latest just@latest aws-cli@latest jq@latest
```

Day-to-day development commands live in [development.md](./development.md).
AWS bring-up and teardown live in [aws.md](./aws.md).

## Raspi Rig Host

The `raspi` rig is the always-on host coordinator that owns Sparkplug
publication for local BLE and Thread-managed devices. Production `raspi` rig
hosts run `txing-sparkplug-manager`, `txing-thread-connectivity`, and
`txing-ble-connectivity` as standalone systemd services.

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
Go `txing-unit-daemon`, native `txing-unit-kvs-master`, and native
`txing-unit-hardware-worker` installed from GitHub Release assets through
`mise`.

Canonical board installation, runtime config, root-owned service setup,
read-only-root layout, manual maintenance, and validation instructions live in
[components/board.md](./components/board.md).

The short production flow is:

1. Flash Raspberry Pi OS Lite 64-bit and boot once with writable root.
2. Enter a root shell on the board.
3. Install OS packages, `NetworkManager`, and root-owned `mise`.
4. Generate the daemon environment/certificate bundle on the operator machine
   with
   `just aws::cert <thing-id>`.
5. Copy and unpack `<thing-id>-daemon-config.tgz` under
   `/root/.config/txing/unit-daemon`, including `daemon.env` and certificate
   files.
6. Install the root-owned mise release tools and create `txing-unit.target`
   with `txing-unit-daemon.service`, `txing-unit-kvs-master.service`, and
   `txing-unit-hardware-worker.service` manually as documented in the board
   guide.
7. Configure the PWM overlay and read-only-root tmpfs layout.
8. Reboot and verify all three board services, KVS readiness, hardware-worker
   readiness, and REDCON convergence.

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
