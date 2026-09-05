# Development

For the system overview, see [../README.md](../README.md). For the documentation map, see [README.md](./README.md).

## Repository Layout

- `devices/unit/`: self-contained current `unit` device type, including MCU, board runtime, rig process implementation, AWS shadow contracts, docs, and web detail adapter
- `rig/`: standalone Go daemons and host tooling for `raspi` rigs
- `devices/cloud-mcu/`: AWS-hosted `cloud` rig and `cloud-mcu` Lambda runtime
- `office/`: React + Vite admin/operator SPA
- `www/`: public static HTML/CSS/assets site for `txing.dev`
- `witness/`: Sparkplug-to-shadow projection Lambda source and tests
- `shared/aws/`: shared AWS CLI helpers, CloudFormation, and registry utilities
- `devices/template/`: scaffold for a new device type using the language-neutral manifest/process/web contracts

## Base Tooling

The supported development host is a current Ubuntu LTS release. Use APT for
system packages, native build dependencies, and Go. Use Mise for the remaining
developer and Codex command-line tools so they stay on current releases. In
particular, Ubuntu's `awscli` package can be v1 while this repository requires
AWS CLI v2.

Install the shared system and build prerequisites:

```bash
sudo apt update
sudo apt install --yes \
  build-essential ccache git ca-certificates cmake curl device-tree-compiler \
  file gcc-arm-none-eabi golang-go gperf ninja-build openocd \
  pkg-config protobuf-compiler python3 python3-venv unzip
```

This provides the native C/C++ build chain, `protoc`, and the Zephyr
MCU host toolchain. The shared MCU recipes require `python3`, `uv`, `cmake`, `ninja`,
`dtc`, `arm-none-eabi-gcc`, `git`, and Go; `uv` provisions their repository-local
Python 3.12 virtual environment. The board proto and native-worker
paths require `protoc`. Generated Go protobuf plugins are pinned and installed
into the repository temporary directory by
`just common::board::proto-gen`, so they are not global prerequisites.

Board Alpine builds and cross-distro smoke tests use a locally installed
`nerdctl` connected to a native Linux/arm64 containerd environment. Verify it
with `nerdctl info --format '{{.OSType}}/{{.Architecture}}'`; it must report
`linux/aarch64` or `linux/arm64`.

Install Mise from its upstream installer, add its activation command to the
shell startup file, then use it for the versioned developer tools:

```bash
curl https://mise.run | sh
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc
source ~/.bashrc
mise use --global aws-cli bun codex gh jq just node ripgrep uv
```

Every tool uses `@latest`; upgrade them with `mise upgrade`.
Mise supplies the Codex CLI and its workflow tools 
(`gh`, `jq`, and Ripgrep's `rg`), AWS CLI v2, Node.js, Bun,
`just`, and `uv`. Go is installed from Ubuntu as `golang-go`. `just` is the
repository task runner and `uv` manages the Python tooling.

To build the board KVS master natively on Ubuntu rather than in the pinned
Alpine container, install its additional system libraries with APT:

```bash
sudo apt install --yes \
  libcurl4-openssl-dev libgrpc++-dev liblog4cplus-dev libprotobuf-dev \
  libsrtp2-dev libssl-dev libusrsctp-dev libwebsockets-dev \
  protobuf-compiler-grpc zlib1g-dev
```

Host-specific setup starts in [installation.md](./installation.md). Detailed
board runtime setup, including read-only rootfs, lives in
[components/board.md](./components/board.md).

## Version And Artifact Channels

Release versions are component-scoped under `release/versions/`. Git SHA and
dirty state are exported separately for diagnostics. Create artifact releases
with `just release::build <component>` after bumping and pushing the managed
component version files yourself. The recipe dispatches the matching GitHub
Actions workflow from the selected branch. Each workflow reads that branch's
component version file, fails unless it is newer than the latest existing tag
with the same component prefix, and publishes only that component's artifacts.
It does not commit or push version changes back to the selected branch.

After a release workflow finishes, the operator Mac deploys CloudFormation
infrastructure changes and then publishes already-built Lambda runtime
artifacts with:

```bash
just aws::deploy
just release::publish lambda
```

Development direction for installable host tools and board-side native
artifacts:

- release artifacts point at the component artifact built from its
  `release/versions/<component>` value, for example `x.y.z`.
- GitHub release assets should be immutable for each exact artifact version.
- Board and rig host binaries use mise's GitHub backend directly; Lambda code
  is uploaded to AWS Lambda from GitHub release assets; see
  [artifacts.md](./artifacts.md).
- Board and rig binary updates are manual writable-root maintenance actions. The
  installed init service starts offline from root-owned mise installs and does
  not call GitHub during normal service restart.
- `latest` is component scoped: rig hosts use `rig-v*`, device-specific board
  tools use `unit-v*` or `cyberbrick-v*`, the shared board KVS master uses
  `kvs-master-v*`, and Lambda publishing uses `lambda-v*`. Existing host mise configs are forward-only manual state;
  replace old configs that do not set the matching `version_prefix` before
  relying on `latest`.
- The Lambda component version covers Go runtime Lambda artifacts only. Release
  builds inject that semver into the Go Lambda binaries, which emit a structured
  cold-start log with `version=<release-version>`. Python admin Lambdas are
  deployed with the current CloudFormation stack code through a
  content-addressed `cfn/aws-admin/<sha>.zip` package.
- Office tracks its version for Cloudflare Pages metadata only. Bump
  `release/versions/office` and the managed office package/runtime surfaces,
  but do not create a GitHub Release or release asset for office.

## Operator AWS Config

Native AWS CLI configuration is the source of truth for AWS account,
credentials, selected profile, and region. `TXING_AWS_STACK` and optional
selected thing IDs come from the operator shell. `TXING_AWS_STACK` is the
environment prefix; the base CloudFormation stack is
`<TXING_AWS_STACK>-aws-base`. The wrapper recipes run plain AWS CLI commands:

- `just aws-town ...`
- `just aws-rig ...`
- `just aws-device ...`

AWS bring-up and destructive rebuild steps live in [aws.md](./aws.md).
Web/admin base stack parameters are initialized separately with
`just aws::deploy-init`; CloudFormation reads the resulting `/txing/stack/*`
SSM Parameter Store values during `aws::deploy`. `just aws::delete` leaves
those manual init parameters in place; `just aws::delete-init` removes only
those final inputs.

## Task Runner

This monorepo uses `just` at the root.

Common commands:

```bash
just --list
just unit::mcu::build
just rig::test
just rig::build
just rig::check <config-dir>
just rig::start
just rig::stop
just common::board::run unit
just office::dev
just office::write-env
just aws::deploy
just aws::deploy-town town
just aws::deploy-rig <town-id> raspi server
just aws::deploy-device <rig-id> unit bot
just aws::shadow <thing>
just aws::shadow-reset <thing>
```

Root modules:

- `rig::...` -> generic rig host tooling in `rig/justfile`
- `unit::...` -> current device type tooling in `devices/unit/justfile`
- `aws::...` -> `shared/aws/justfile`
- `office::...` -> `office/justfile`
- `witness::...` -> `witness/justfile`

## Current Named Shadows

Named shadows are selected from the thing's AWS IoT ThingType and the
CloudFormation-managed SSM type catalog under `/txing`.

Current capabilities:

- `town`: `sparkplug`
- `raspi`: `sparkplug`
- `cloud`: `sparkplug`
- `unit`: `sparkplug`, `ble`, `power`, `board`, `mcp`, `video`
- `cloud-mcu`: `sparkplug`, `sqs`, `power`, `ecs`
- `weather`: `sparkplug`, `ble`, `power`, `weather`
- `power`: `sparkplug`, `ble`, `power`

There is no `device` named shadow in the current implementation.

Useful commands:

```bash
just aws::shadow <thing>
just aws::shadow <thing> sparkplug
just aws::shadow-reset <thing>
just aws::shadow-reset <thing> mcp
```

`aws::shadow-reset` deletes the classic unnamed shadow, removes known named
shadows that are not valid for the thing's type catalog capabilities, and
reseeds device named shadows from the default payloads declared in
`devices/<type>/manifest.toml`.

## Common Development Loops

MCU:

```bash
just mcu::check
just unit::mcu::build
```

Rig:

```bash
just rig::test
just rig::build
just rig::start
just rig::log
just rig::stop
```

`just rig::start` runs only the Sparkplug manager (the `local` rig default)
and reads config from `TXING_RIG_CONFIG_DIR` or `~/.config/txing/rig-daemon`;
pass a config directory and `all` to also start the Thread and BLE daemons.

That source-checkout rig loop is for development. Production `raspi` rig hosts
publish GitHub release assets through root-owned `mise` and systemd via
`just release::publish rig`. Production `cloud` rig infrastructure is deployed
through `just aws::deploy`; its runtime Lambda code is published from GitHub
release artifacts with `just release::publish lambda`.

Board:

```bash
just common::board::run unit
just common::board::test unit
just common::board::kvs-build-native
just common::board::kvs-test-native
just common::board::kvs-build-alpine
just common::board::hardware-build-native unit
just common::board::hardware-test-native unit
just common::board::hardware-build-alpine unit
just common::board::daemon-build-alpine unit
just common::board::nerdctl-build unit
just common::board::nerdctl-smoke unit
```

The Go unit daemon loads its default config from
`${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}/daemon.env`
and expects certificate files in the same directory unless explicit certificate
path overrides are supplied. Provision that directory with
`just aws::cert <thing-id>` only when AWS resource changes are
intended; the recipe renders systemd-compatible `daemon.env` content from
`devices/common/daemon.env.template` and refuses to overwrite existing
daemon env or certificate material.

The deployed board runtime, MCP/video transport contract, and board install
flow are documented in [components/board.md](./components/board.md).

Office:

```bash
just office::install
just office::write-env
just office::dev
```

Public site:

```bash
cd www
python3 -m http.server 5174
```

Witness:

```bash
just witness::test
```

## Contracts

The current implementation contracts are:

- [Sparkplug lifecycle](./sparkplug-lifecycle.md)
- [Unit thing shadow model](../devices/unit/docs/thing-shadow.md)
- [Unit device-rig shadow contract](../devices/unit/docs/device-rig-shadow-spec.md)
- [Shared board video contract](./components/board-video.md)
