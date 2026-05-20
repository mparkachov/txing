# Installation

This page is the host setup index. Detailed runtime setup lives with the
component that owns the host behavior.

## Shared Assumptions

- Development machines may use a repository checkout.
- Production board hosts install release artifacts with `mise` and do not need a
  source checkout for the release runtime path.
- Production rig hosts receive txing components through Greengrass cloud
  deployments and do not need a source checkout, `mise`, AWS CLI, or AWS access
  keys.
- Operator AWS account, credentials, profile selection, and region come from
  native AWS CLI configuration.
- Stack-backed operator commands and deploys fail unless `TXING_AWS_STACK` is
  set explicitly in the operator environment or passed as a positional stack
  name where supported.
- The one-off `just aws::deploy-init` step stores web/admin deploy parameters
  from `shared/aws/deploy-init.json` as separate `/txing/stack/*` SSM Parameter
  Store values before the first base stack deployment.

## Development Machine

Repo-wide developer tooling:

- `uv`
- `just`
- `jq`
- AWS CLI v2
- GitHub CLI (`gh`) for operator-side release, Lambda, and Greengrass deploys

Install operator CLIs with the package manager you use for the development
machine. `mise` is acceptable for missing or stale CLI versions:

```bash
mise use --global uv@latest just@latest aws-cli@latest gh@latest jq@latest
```

Day-to-day development commands live in [development.md](./development.md).
AWS bring-up and teardown live in [aws.md](./aws.md).

## Rig Host

The rig is the always-on coordinator that owns Sparkplug publication. Production
rig hosts run the official AWS Greengrass Lite Debian package plus txing
Greengrass components delivered by cloud deployments.

Canonical rig installation, Greengrass Lite configuration, Bluetooth
permission, deployment, health-check, update, and cleanup instructions live in
[components/rig.md](./components/rig.md).

The short production flow is:

1. Install the upstream Greengrass Lite Debian package on the rig.
2. Add `gg_component` to the OS `bluetooth` group for `RIG_TYPE=raspi`.
3. Generate `config/certs/rig/` certificate material and
   `greengrass-lite.yaml` on the operator machine.
4. Copy `rig.cert.pem`, `rig.private.key`, `AmazonRootCA1.pem`, and
   `greengrass-lite.yaml` to the Greengrass locations on the rig.
5. Restart `greengrass-lite.target`.
6. Deploy txing components from the operator machine with
   `just rig::deploy-release latest all`.

## Board Host

The board is the device-side Raspberry Pi. Production boards run the root-owned
Rust `txing-unit-daemon` and native `txing-board-kvs-master` installed from
GitHub Release assets through `mise`.

Canonical board installation, runtime config, root-owned service setup,
read-only-root layout, manual maintenance, and validation instructions live in
[components/board.md](./components/board.md).

The short production flow is:

1. Flash Raspberry Pi OS Lite 64-bit and boot once with writable root.
2. Enter a root shell on the board.
3. Install OS packages, `NetworkManager`, and root-owned `mise`.
4. Generate daemon config/cert material on the operator machine with
   `just unit::cert <thing-id>`.
5. Copy and unpack `<thing-id>-daemon-config.tgz` under
   `/root/.config/txing/unit-daemon`, including `daemon.env` and certificate
   files.
6. Install the root-owned mise release tools and
   `txing-unit-daemon.service` manually as documented in the board guide.
7. Configure the PWM overlay and read-only-root tmpfs layout.
8. Reboot and verify `txing-unit-daemon.service`, KVS readiness, and REDCON
   convergence.

## Web

The operator/admin SPA is documented in [components/web.md](./components/web.md).

Local development:

```bash
just web::install
just web::write-env
just web::dev
```

Production deployment is Cloudflare Pages from the `web` directory.

## Public Site

The public site is documented in [components/site.md](./components/site.md).

Local development:

```bash
cd site
bun install
bun run dev
```
