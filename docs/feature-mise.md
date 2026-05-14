# Feature Mise Release Architecture

This document captures the architecture decision for installing and testing
`unit` daemon releases with `mise`. It is intended as the source material for a
later implementation plan.

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

## Non-Goals

- No AWS IoT, shadow, MQTT, or fleet-control mechanism for selecting the feature
  channel.
- No `.deb` package in the first implementation.
- No custom mise plugin in the first implementation.
- No source repository, `just` tasks, or project checkout on the board.
- No branch-specific feature channel yet.
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
- Asset: one Linux `aarch64` dynamically linked executable.
- Asset command exposed by mise: `txing-unit-daemon`.

Feature releases are GitHub prereleases:

- Tag/release name: repo-wide prerelease version, for example
  `v0.9.9-dev.20260514T153000Z.gabc1234.dirtyabcd`.
- Version source: the next patch version after the current base `VERSION`, plus
  a timestamp and git state suffix.
- Built locally by a developer in a Linux `aarch64` environment.
- Functional tests are mandatory before publish.
- GitHub prerelease flag: `true`.
- Asset: one Linux `aarch64` dynamically linked executable.
- Retention: keep the latest 10 feature prereleases globally.

Feature releases are intentionally shared and temporary. Developers may overwrite
each other's latest feature channel. Branch-specific feature channels can be
added later if that becomes painful.

## Version Ordering

Feature builds should be prereleases of the next stable version, not build
metadata on the current stable version.

If stable is `0.9.8`, a feature build should look like:

```text
0.9.9-dev.20260514T153000Z.gabc1234.dirtyabcd
```

This gives the desired ordering:

- `0.9.9-dev...` is newer than stable `0.9.8`, so a feature-opt-in board can run
  it.
- Stable `0.9.9` is newer than `0.9.9-dev...`, so once `main` advances and CI
  publishes stable, stable naturally wins.
- If `main` advances farther, for example to `0.10.0`, old feature prereleases
  are also naturally behind stable.

This keeps feature work tied to the current stable base and avoids long-lived
feature artifacts pretending to be newer than later production releases.

## Board Installation Model

The board has a dedicated `txing` user. Mise is installed for that user and runs
as that user. The systemd service is created once during manual board setup.

Persistent stable state lives under the user's home directory:

```text
/home/txing/.config/mise/
/home/txing/.local/share/mise/
/home/txing/.cache/mise/
```

These paths are on the read-only root during normal boot. They are updated only
during a manual writable maintenance window.

Feature state is ephemeral and lives under `/run` during boot:

```text
/run/txing/mise
/run/txing/mise-cache
/run/txing/mise-tmp
```

Feature artifacts disappear on reboot. Every feature-opt-in boot may attempt to
install the latest applicable feature release into `/run`.

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

## Feature Opt-In Boot Flow

Feature channel selection is manual and local to the board. It is not controlled
by AWS or the fleet runtime.

A feature-opt-in board uses a separate mise config for the daemon systemd
service. The service points mise's primary data/cache/tmp directories at `/run`,
and exposes the persistent stable installs as a read-only shared install
directory.

Conceptual systemd shape:

```ini
User=txing
Group=txing

Environment=MISE_GLOBAL_CONFIG_FILE=/home/txing/.config/mise/txing-unit-daemon-feature.toml
Environment=MISE_DATA_DIR=/run/txing/mise
Environment=MISE_CACHE_DIR=/run/txing/mise-cache
Environment=MISE_TMP_DIR=/run/txing/mise-tmp
Environment=MISE_SHARED_INSTALL_DIRS=/home/txing/.local/share/mise/installs
Environment=MISE_PRERELEASES=1

ExecStartPre=-/usr/bin/timeout 10s /home/txing/.local/bin/mise install
ExecStart=/home/txing/.local/bin/mise exec --offline -- txing-unit-daemon
```

The exact unit should use absolute paths and the current installed mise location.
The snippet is a behavioral sketch, not a final unit file.

Expected behavior:

- If feature install succeeds and the feature prerelease is newer than stable,
  `mise exec --offline` runs the feature binary from `/run`.
- If feature install fails or times out, the `-` prefix lets systemd continue,
  and `mise exec --offline` runs the latest persistent stable binary.
- If stable has advanced beyond the feature prerelease, stable wins through
  normal version ordering.
- `ExecStart` is offline, so the actual daemon start does not perform network
  resolution or install work.

This avoids a custom wrapper script while still providing ephemeral feature
installs and persistent stable fallback.

## Local Feature Publishing

Most developers use Apple Silicon Macs. Direct macOS-to-Linux dynamic glibc
cross-linking is not the first-choice workflow. The recommended first workflow is
a persistent Linux `aarch64` Lima VM with the repository checkout and build
tooling installed inside the VM.

From macOS, the intended developer command shape is:

```bash
limactl shell txing -- bash -lc 'cd /path/to/txing && just unit::daemon::prerelease'
```

The `unit::daemon::prerelease` implementation should run inside Linux and:

- verify the feature version derived from root `VERSION`, timestamp, git SHA,
  and dirty hash;
- run mandatory functional tests;
- build the release binary for Linux `aarch64`;
- create a GitHub prerelease;
- upload the single executable asset;
- prune feature prereleases to the latest 10 globally.

Dirty working trees are allowed. Dirty builds must include dirty state in the
prerelease version so two local states do not publish as the same version.

## Stable CI Publishing

Stable publishing is CI-owned:

- Trigger: merge to `main` where root `VERSION` changed.
- Version: root `VERSION` exactly.
- Release: repo-wide `v<VERSION>`.
- GitHub prerelease flag: `false`.
- Build target: Linux `aarch64` dynamic binary for the current supported board
  baseline.
- Asset command: `txing-unit-daemon`.
- Existing stable releases and assets are immutable. CI should fail or skip
  rather than replace a release asset for an already-published version.

Before this can be trusted, the daemon's Cargo package version needs to be
managed by the repo release tooling so `devices/unit/daemon/Cargo.toml` and
`devices/unit/daemon/Cargo.lock` match root `VERSION`.

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
creation remains a one-time manual setup step for now.

### Use `/run` For Feature Installs

The root filesystem is read-only during normal boot. `/run` is tmpfs-backed and
appropriate for boot-lifetime runtime state. Existing `/tmp` sizing is small, so
feature mise state should not consume `/tmp`.

### Keep Stable In The User Home

The onboarding model is intentionally simple: image the board, create/login as
the user, install mise, configure credentials and mise, run upgrades, then switch
the root back to read-only. Keeping mise under `/home/txing` matches normal mise
usage and avoids system-wide tool management.

### Run As The Dedicated `txing` User

Mise installation, feature install, and daemon execution should all happen as the
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

- Add daemon version surfaces to release tooling so root `VERSION`, Cargo
  manifest, and lockfile agree.
- Decide the installed command name and release asset naming convention.
- Add a local Linux `aarch64` prerelease recipe for the daemon.
- Run the mandatory daemon tests in that prerelease recipe.
- Build a dynamically linked Linux `aarch64` binary.
- Publish a GitHub prerelease with a single executable asset.
- Manually configure one board with mise stable config and one feature service
  config.
- Verify stable install through mise.
- Verify feature boot install into `/run`.
- Verify fallback to stable when feature install fails.
- Verify stable wins after publishing a stable version newer than the feature
  prerelease base.

This phase can tolerate manual board setup and rough commands. The success
criterion is that a developer can build locally in Lima, publish a feature
prerelease, reboot an opted-in board, and see the daemon run that binary without
a source checkout on the board.

### Phase 2: Repeatable Stable Installation

Goal: make stable board setup and maintenance boring and repeatable.

- Add CI publishing for stable releases on `main` when `VERSION` changes.
- Make stable release assets immutable.
- Document the initial board setup from fresh Raspberry Pi OS image through
  dedicated `txing` user, mise install, stable tool config, certificates, and
  systemd unit creation.
- Document the stable maintenance command sequence:
  `root-rw`, `apt update`, `apt dist-upgrade`, `mise upgrade`, manual restart,
  `root-ro`.
- Document expected filesystem writes during stable maintenance and normal boot.
- Add a stable-only systemd unit that launches through `mise exec --offline`.
- Verify stable-only boot on read-only root.
- Verify stable upgrade while root is writable and service restart after upgrade.

This phase should leave production-like stable boards understandable and
repeatable without requiring feature-channel knowledge.

### Phase 3: Channel Polish And Operational Features

Goal: improve safety and developer ergonomics after the core path works.

- Automate pruning to the latest 10 feature prereleases globally.
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

## Open Questions For Implementation

- Exact stable and feature mise config file contents.
- Exact systemd unit and drop-in layout.
- Exact functional test set required before local prerelease publish.
- Exact Lima image and provisioning requirements.
- Exact GitHub release asset name pattern for future multi-architecture support.
