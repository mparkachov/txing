# Feature Mise Release Architecture

This document captures the architecture decision for installing and testing
`unit` daemon releases with `mise`. Phase 1 is implemented: feature builds are
published as GitHub prereleases, and opted-in boards install and run them through
`mise` plus systemd without a source checkout.

The operational phase-1 runbook is
[feature-mise-impl.md](./feature-mise-impl.md).

## Goals

- Install `unit` daemon binaries without keeping a source checkout on the board.
- Keep the normal board root filesystem read-only after initial setup.
- Let a developer manually opt a board into a temporary feature channel.
- Let stable maintenance feel like normal package maintenance:
  `root-rw`, `apt` upgrade, `mise upgrade`, then manual service restart when
  desired.
- Avoid building on the board.
- Keep local feature publish fast for Apple Silicon developers.
- Use dynamic Linux binaries and the target OS userspace where practical, rather
  than static musl builds.
- Keep the first implementation narrow: `aarch64` Linux for current Raspberry Pi
  OS Trixie-class boards.

## Phase Status

- Phase 1 end-to-end feature workflow: implemented and manually verified on a
  Raspberry Pi Zero 2 W with read-only root.
- Phase 2 stable CI publishing: initial GitHub Actions workflow implemented.
- Phase 2 stable fallback behavior: pending.
- Phase 3 channel polish and operational improvements: pending.

## Non-Goals

- No AWS IoT, shadow, MQTT, or fleet-control mechanism for selecting the feature
  channel.
- No `.deb` package in the first implementation.
- No custom mise plugin in the first implementation.
- No source repository, `just` tasks, or project checkout on the board.
- No automatic branch-specific feature channel yet.
- No integrity enforcement beyond GitHub Releases over HTTPS yet.
- No automatic daemon restart after `mise upgrade` during stable maintenance.

## External Mechanisms

The design uses standard mise features:

- GitHub release assets through the mise GitHub backend:
  <https://mise.jdx.dev/dev-tools/backends/github.html>
- `mise upgrade` for normal installed-tool updates:
  <https://mise.jdx.dev/cli/upgrade.html>
- `mise exec` for launching the configured tool:
  <https://mise.jdx.dev/cli/exec.html>
- mise data/cache/config directory environment variables:
  <https://mise.jdx.dev/directories.html>
- mise `prereleases`, `offline`, and `shared_install_dirs` settings:
  <https://mise.jdx.dev/configuration/settings.html>

## Release Channels

There is one tool from the board's point of view: `txing-unit-daemon`.

Stable releases are normal GitHub releases:

- Tag/release name: repo-wide `v<VERSION>`, for example `v0.9.8`.
- Version source: repo root `VERSION`.
- Built by CI from `main` when `VERSION` changes.
- GitHub prerelease flag: `false`.
- Asset: one `.tar.gz` archive containing a stripped Linux `aarch64`
  dynamically linked executable named `txing-unit-daemon`.
- Asset command exposed by mise: `txing-unit-daemon`.

Feature releases are GitHub prereleases:

- Tag/release name: repo-wide prerelease version, for example
  `v0.9.9-feature.1770000000`.
- Version source: the next patch version after the current base `VERSION`, plus
  a Unix timestamp prerelease suffix.
- Built locally by a developer in a Linux `aarch64` environment, then published
  from macOS where GitHub CLI authentication is available.
- Functional tests are mandatory before publish.
- GitHub prerelease flag: `true`.
- Asset: one `.tar.gz` archive containing a stripped Linux `aarch64`
  dynamically linked executable named `txing-unit-daemon`.
- Retention: keep the latest 10 feature prereleases globally.

Feature releases are intentionally shared and temporary. Developers may overwrite
each other's latest feature channel. Branch-specific feature channels can be
added later if that becomes painful.

## Version Ordering

Feature builds should be prereleases of the next stable version, not build
metadata on the current stable version.

If stable is `0.9.8`, a feature build should look like:

```text
0.9.9-feature.1770000000
```

This gives the desired ordering:

- `0.9.9-feature...` is newer than stable `0.9.8`, so a feature-opt-in board can
  run it.
- Stable `0.9.9` is newer than `0.9.9-feature...`, so once `main` advances and
  CI publishes stable, stable naturally wins.
- If `main` advances farther, for example to `0.10.0`, old feature prereleases
  are also naturally behind stable.

This keeps feature work tied to the current stable base and avoids long-lived
feature artifacts pretending to be newer than later production releases.

## Board Installation Model

The board has a dedicated `txing` user. Mise is installed for that user and runs
as that user. The raw repository installer creates or updates the systemd
service during a writable maintenance window.

Persistent daemon config lives under the user's home directory and is provisioned
during a writable maintenance window:

```text
/home/txing/.config/mise/
/home/txing/.config/txing/unit-daemon/
```

The unit daemon runtime config uses the same per-user layout on macOS and
Linux:

```text
${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}
```

The implemented config filename is `.env`. It is directly sourceable and lives
beside the daemon certificate material:

```text
.env
AmazonRootCA1.pem
certificate.arn
certificate.pem.crt
private.pem.key
public.pem.key
```

The generated `.env` contains host-independent runtime values, including the IoT
endpoints, role alias, and CloudWatch log settings. It intentionally does not
contain certificate paths; the daemon derives the default certificate paths from
the directory of the loaded `.env` file. Explicit CLI flags or environment
variables can still override those paths.

These paths are on the read-only root during normal boot. They are updated only
during a manual writable maintenance window.

Feature install/cache/tmp state is ephemeral and lives under `/var/tmp` on the
existing executable tmpfs from the read-only-root provisioning:

```text
/var/tmp/txing/unit-daemon/mise
/var/tmp/txing/unit-daemon/mise-cache
/var/tmp/txing/unit-daemon/mise-tmp
```

Every daemon service boot may attempt to install or refresh the selected mise
channel before starting the daemon offline.

## Stable Maintenance Flow

On a stable-only board, the developer performs maintenance manually:

```bash
root-rw
sudo apt update
sudo apt dist-upgrade -y
mise upgrade
```

The daemon is not restarted automatically by this flow. The developer can
restart the service manually when appropriate.

The stable mise config should exclude prereleases. That keeps `mise upgrade`
equivalent to "install latest stable".

## Unit Daemon Service Install

Channel selection is manual and local to the board. It is not controlled by AWS
or the fleet runtime.

The implemented phase-1 board installer is a raw repository script, not a
GitHub release asset:

```text
devices/unit/daemon/install-systemd.sh
```

Run it during a writable-root maintenance window. Feature installs use the
current feature branch copy of the script:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/feature/unit-daemon-prerelease/devices/unit/daemon/install-systemd.sh | sudo bash -s -- feature
```

Stable installs use `main` once stable daemon release assets exist:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh | sudo bash -s -- stable
```

Both channels use the same systemd unit and mise config path:

```text
/etc/systemd/system/txing-unit-daemon.service
/home/txing/.config/mise/txing-unit-daemon/config.toml
```

Feature channel config:

```toml
[tool_alias]
txing-unit-daemon = "github:mparkachov/txing"

[tools.txing-unit-daemon]
version = "latest"
asset_pattern = "txing-unit-daemon-linux-aarch64.tar.gz"
prerelease = true

[settings.github]
slsa = false
github_attestations = false
```

Stable channel config:

```toml
[tool_alias]
txing-unit-daemon = "github:mparkachov/txing"

[tools.txing-unit-daemon]
version = "latest"
asset_pattern = "txing-unit-daemon-linux-aarch64.tar.gz"
prerelease = false
```

With `prerelease = true`, feature mode resolves `latest` to the newest GitHub
release including prereleases. With `prerelease = false`, stable mode resolves
only normal releases. The asset name and exposed command stay stable. The
archive contains `txing-unit-daemon` at its root, so mise discovers that
executable after extraction without `bin` or `rename_exe`. The `tool_alias`
makes mise report the tool as `txing-unit-daemon` instead of the backend key
`github:mparkachov/txing`. SLSA and GitHub artifact attestations are disabled
only for feature mode because the asset is built locally in Lima and uploaded by
`gh`; stable CI publishing should revisit attestations.

The installer writes the service with
`Wants=network-online.target systemd-time-wait-sync.service` and
`After=network-online.target systemd-time-wait-sync.service time-sync.target`,
then this service shape with absolute paths:

```ini
User=txing
Group=txing

Environment=MISE_CONFIG_DIR=/home/txing/.config/mise/txing-unit-daemon
Environment=MISE_DATA_DIR=/var/tmp/txing/unit-daemon/mise
Environment=MISE_CACHE_DIR=/var/tmp/txing/unit-daemon/mise-cache
Environment=MISE_TMP_DIR=/var/tmp/txing/unit-daemon/mise-tmp
Environment=TXING_DAEMON_CONFIG_DIR=/home/txing/.config/txing/unit-daemon
Environment=HOME=/home/txing

ExecStartPre=/usr/bin/install -d -m 700 /var/tmp/txing/unit-daemon/mise /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp
ExecStartPre=/home/txing/.local/bin/mise install
ExecStartPre=-/usr/bin/find /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp -mindepth 1 -maxdepth 1 -exec rm -rf {} +
ExecStart=/usr/bin/env MISE_OFFLINE=1 /home/txing/.local/bin/mise exec -- txing-unit-daemon
```

Feature mode additionally sets `MISE_PRERELEASES=1` in the rendered unit.

Expected behavior:

- `mise install` runs after network-online and clock synchronization, before
  daemon start, and writes install/cache/tmp state under
  `/var/tmp/txing/unit-daemon` on the executable tmpfs.
- In phase 1, install failure makes service start fail visibly. Stable fallback
  should be designed after stable release publishing is in place.
- `ExecStart` is offline, so the actual daemon start does not perform network
  resolution or install work.

This keeps installed executables on an existing writable executable filesystem
even when the board root is read-only.

## Local Feature Publishing

Most developers use Apple Silicon Macs. Direct macOS-to-Linux dynamic glibc
cross-linking is not the first-choice workflow. The recommended first workflow is
a persistent Linux `aarch64` Lima VM with the repository checkout and build
tooling installed inside the VM.

The Lima login shell should activate mise so `just`, `cargo`, and other tools
are on `PATH` without wrapping each command:

```bash
cat >> ~/.bashrc <<'EOF'
export PATH="$HOME/.local/bin:$PATH"
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
fi
EOF
exec bash
```

If the current shell has not been reloaded yet, run the build command through
`mise exec --` instead of bare `just`.

From macOS, log in to the Lima builder and run the Linux build step manually:

```bash
limactl shell txing
cd /path/to/txing
just unit::daemon::prerelease-build
exit
```

Current-shell fallback before `.bashrc` activation is active:

```bash
mise exec -- just unit::daemon::prerelease-build
```

Then publish from macOS, where `gh` is authenticated:

```bash
just unit::daemon::prerelease-publish
```

The `unit::daemon::prerelease-build` implementation runs inside Linux and:

- requires Linux `aarch64`;
- requires Lima build tools including `cargo`, `file`, `git`, and `python3`;
- requires a clean git worktree, including untracked files;
- derives the feature version from the next patch after root `VERSION` plus a
  Unix timestamp: `v<NEXT_PATCH>-feature.<timestamp>`;
- run mandatory functional tests;
- build the release binary for Linux `aarch64`;
- embed the feature version into the daemon startup log;
- strip it;
- stage it as `txing-unit-daemon-linux-aarch64.tar.gz`, containing a root-level
  `txing-unit-daemon` executable;
- write JSON metadata for the macOS publish step.

The `unit::daemon::prerelease-publish` implementation runs on macOS and:

- requires a clean git worktree;
- verifies the current `HEAD` matches the build metadata;
- pushes `HEAD` to a moving branch under `feature/`;
- pushes the timestamped prerelease tag;
- creates the GitHub prerelease and uploads the staged asset;
- prunes older unit-daemon feature prereleases so only the latest 10 remain.

Dirty or untracked work must be committed before publishing. The feature branch
is intentionally moving; the default branch name is
`feature/unit-daemon-prerelease`.

## Stable CI Publishing

Stable publishing is CI-owned:

- Workflow: `.github/workflows/unit-daemon-stable-release.yml`.
- Current trigger: manual `workflow_dispatch` only.
- Allowed manual refs: `main` and temporary phase-2 branch
  `feature/build-daemon-for-txing`.
- Version: root `VERSION` exactly.
- Release: repo-wide `v<VERSION>`.
- GitHub prerelease flag: `false`.
- Build target: Linux `aarch64` dynamic binary for the current supported board
  baseline.
- Asset command: `txing-unit-daemon`.
- Asset archive: `txing-unit-daemon-linux-aarch64.tar.gz`, containing a
  root-level `txing-unit-daemon` executable.
- Existing stable tags, releases, and assets are immutable. CI fails rather than
  replacing a tag, release, or asset for an already-published version.

The workflow builds natively on GitHub's Linux `aarch64` runner, runs daemon
tests, packages the archive, and publishes a normal GitHub Release. It caches the
Rust toolchain, Cargo downloads, and the daemon `target` directory with cache
keys scoped to Rust `1.95.0` and `devices/unit/daemon/Cargo.lock`.

The daemon Cargo package version is managed by the repo release tooling:
`release::bump` updates `devices/unit/daemon/Cargo.toml` and the daemon package
entry in `devices/unit/daemon/Cargo.lock`, and `release::check` validates both
against the repo root `VERSION`.

## Implemented Phase 1 Baseline

The current phase-1 implementation has these working pieces:

- `just unit::daemon::cert <thing-id>` provisions daemon certificate material
  and writes `.env` plus the certificate files into the per-user
  `txing/unit-daemon` config directory. The recipe refuses to overwrite existing
  `.env` or certificate material.
- The generated `.env` uses `export KEY=value` lines and includes CloudWatch log
  group, level, and retention settings.
- `just unit::daemon::run` runs
  `cargo run --manifest-path devices/unit/daemon/Cargo.toml` from the repository
  root.
- `just unit::daemon::prerelease-build` stages a clean-tree Linux `aarch64`
  stripped feature binary archive and JSON metadata under
  `devices/unit/daemon/target/prerelease`.
- The daemon startup log includes `version=<version>`, using the exact feature
  prerelease version when built by `unit::daemon::prerelease-build`.
- `just unit::daemon::prerelease-publish` runs on macOS, pushes the
  `feature/unit-daemon-prerelease` branch and `v<NEXT_PATCH>-feature.<timestamp>`
  tag, creates the GitHub prerelease, uploads
  `txing-unit-daemon-linux-aarch64.tar.gz`, and keeps only the latest 10 matching
  unit-daemon feature prereleases.
- The daemon lookup order is `--env-file`, `TXING_DAEMON_ENV_FILE`,
  `TXING_DAEMON_CONFIG_DIR/.env`, `XDG_CONFIG_HOME/txing/unit-daemon/.env`, then
  `$HOME/.config/txing/unit-daemon/.env`.
- When certificate path variables are absent, the daemon loads
  `certificate.pem.crt`, `private.pem.key`, and `AmazonRootCA1.pem` from the
  same directory as the loaded `.env`.
- A macOS foreground run through `just unit::daemon::run` uses the same generated
  local config path as the board service.
- The daemon publishes the retained `board` capability state when it starts
  successfully.
- The generic daemon installer writes
  `/home/txing/.config/mise/txing-unit-daemon/config.toml`; feature mode uses
  `version = "latest"` with `prerelease = true`, and stable mode uses
  `version = "latest"` with `prerelease = false`.
- The generic daemon installer writes `txing-unit-daemon.service`; service start
  waits for network-online and clock synchronization, downloads
  `txing-unit-daemon-linux-aarch64.tar.gz`, extracts the daemon under
  `/var/tmp/txing/unit-daemon/mise`, starts it offline, and logs
  `version=<version>` on startup.
- `release::bump` and `release::check` include the daemon Cargo manifest and
  lockfile.

## Architecture Decisions

### Use mise Instead Of A Custom Package Manager

Mise gives the desired user workflow: developer-controlled tool installation,
simple updates, and no board-side source checkout. It also leaves OS packages to
`apt`, which remains responsible for system libraries and base OS security
updates.

### Use GitHub Releases First

The repository is public, so GitHub Releases are the cheapest no-infrastructure
artifact host. Mise has a native GitHub backend, and GitHub prerelease metadata
maps cleanly to the feature channel.

S3 or another object store can be revisited if GitHub API rate limits, retention,
or workflow constraints become real problems. Avoid introducing cloud artifact
infrastructure before it is needed.

### Avoid A Custom Mise Plugin Initially

The GitHub backend already supports release assets, asset selection, prerelease
handling, and single-binary installs. A custom plugin would add moving parts
before there is a concrete need.

### Avoid `.deb` Initially

A Debian package is attractive for stable fleet deployment, but it adds package
repository, signing, and system-file ownership questions. The current goal is a
developer-friendly binary channel with read-only-root compatibility. Systemd unit
creation is handled by the raw repository installer script.

### Use `/var/tmp` For Service Installs

The root filesystem is read-only during normal boot. `/tmp` and `/var/tmp` are
already tmpfs-backed in the board provisioning. `/tmp` is intentionally small and
is used for board runtime sockets and state, so daemon mise state should not
consume it. `/var/tmp` is the existing general-purpose writable tmpfs, so it is
the right place for boot-lifetime install/cache/tmp state as long as the
provisioned size is increased and `exec` remains allowed. Use a tight cap, for
example `96M`, on Raspberry Pi Zero 2 W boards.

### Keep Service Config In The User Home

The onboarding model is intentionally simple: image the board, create/login as
the user, install mise, configure credentials and mise config, run upgrades, then
switch the root back to read-only. Keeping service config under `/home/txing`
matches normal mise usage and avoids system-wide tool configuration. The
downloaded daemon executable itself lives under `/var/tmp` during phase 1.

### Run As The Dedicated `txing` User

Mise installation, daemon install, and daemon execution should all happen as the
same dedicated user. This avoids root-owned files in the user's mise directories
and keeps the daemon out of the login user's personal account.

### Keep Current Rust TLS Dependencies

The first implementation should keep the current daemon dependency model. Moving
TLS/crypto to system OpenSSL is a separate code dependency decision and should
not block the release architecture.

### Build In Linux For Local Feature Releases

The target artifact is a dynamic Linux binary. Building inside a Linux `aarch64`
VM is a pragmatic way to avoid fragile macOS cross-linker setup while keeping the
developer command fast and predictable.

## Three-Phase Implementation Plan

### Phase 1: End-To-End Feature Workflow

Goal: prove the entire loop works before polishing repeatability.

Status: complete for the feature channel.

- Add daemon version surfaces to release tooling so root `VERSION`, Cargo
  manifest, and lockfile agree. Implemented for `release::bump` and
  `release::check`.
- Decide the installed command name and release asset naming convention.
  Implemented as command `txing-unit-daemon` and asset
  `txing-unit-daemon-linux-aarch64.tar.gz`.
- Add per-user daemon config loading from `.env` with colocated certificate
  defaults. Implemented for local macOS and Linux board runs.
- Add a local foreground run recipe for source checkout development.
  Implemented as `just unit::daemon::run`.
- Add a local Linux `aarch64` prerelease recipe for the daemon. Implemented as
  `just unit::daemon::prerelease-build`.
- Run the mandatory daemon tests in that prerelease recipe. Implemented in
  `just unit::daemon::prerelease-build`.
- Build a dynamically linked Linux `aarch64` binary. Implemented in
  `just unit::daemon::prerelease-build`.
- Publish a GitHub prerelease with a single `.tar.gz` archive asset. Implemented
  in `just unit::daemon::prerelease-publish`.
- Add a generic raw-repository systemd installer for the daemon service.
  Implemented as `devices/unit/daemon/install-systemd.sh`.
- Install a clean board with the generic service in feature mode. Verified.
- Verify feature boot install into `/var/tmp`. Verified.
- Verify daemon service start through systemd with startup version logging and
  retained online state publish. Verified.
- Stable mode is supported by the installer, but stable release publishing,
  stable fallback, and stable-wins behavior remain phase 2.

The success criterion is that a developer can build locally in Lima, publish a
feature prerelease, run the raw installer in feature mode, reboot an opted-in
board, and see the daemon run that binary without a source checkout on the
board. This criterion is met for phase 1.

### Phase 2: Repeatable Stable Installation

Goal: make stable board setup and maintenance boring and repeatable.

- Add CI publishing for stable releases. Implemented as manual
  `.github/workflows/unit-daemon-stable-release.yml`; temporary phase-2 manual
  runs from `feature/build-daemon-for-txing` are also allowed.
- Make stable release assets immutable. Implemented in the workflow.
- Document the initial board setup from fresh Raspberry Pi OS image through
  dedicated `txing` user, mise install, stable tool config, certificates, and
  systemd unit creation.
- Document the stable maintenance command sequence:
  `root-rw`, `apt update`, `apt dist-upgrade`, `mise upgrade`, manual restart,
  `root-ro`.
- Document expected filesystem writes during stable maintenance and normal boot.
- Verify the generic systemd unit in stable mode once stable release assets
  exist.
- Verify stable-only boot on read-only root.
- Verify stable upgrade while root is writable and service restart after upgrade.

This phase should leave production-like stable boards understandable and
repeatable without requiring feature-channel knowledge.

### Phase 3: Channel Polish And Operational Features

Goal: improve safety and developer ergonomics after the core path works.

- Add clearer journald messages around feature install success, timeout, and
  fallback.
- Add a documented manual opt-in/opt-out procedure for feature mode.
- Add branch-specific or pinned feature channels if developers need isolation.
- Add additional architectures through Rust target and release-asset matrices.
- Consider an alternate artifact host only if GitHub rate limits or release
  management become painful.
- Consider checksums or attestations if integrity requirements increase.
- Revisit system OpenSSL or other system-library linkage only as a daemon
  dependency decision.
- Revisit `.deb` packaging only if stable fleet deployment needs OS package
  semantics.

## Remaining Questions

- Stable release publishing workflow and attestation policy.
- Stable service fallback behavior when install or network resolution fails.
