# Feature Mise Phase 1 Implementation

This runbook documents the completed phase-1 implementation from
[feature-mise.md](./feature-mise.md): local Linux `aarch64` feature builds,
macOS GitHub prerelease publishing, and a raw-repository systemd installer for
the board.

The final path does not build on the Raspberry Pi board, does not copy a source
checkout to the board, and does not use `/etc/txing` for daemon runtime config.

## Final Configuration

### Host Roles

- macOS development host:
  - owns the source checkout;
  - provisions daemon config and certificate material when explicitly requested;
  - drives Docker prerelease builds through the Lima Docker socket;
  - publishes GitHub prereleases through authenticated `gh`.
- Docker prerelease builder on Lima Linux `aarch64`:
  - receives the source checkout as a read-only bind mount at the same absolute
    path used on macOS and Lima;
  - uses Docker volumes for Cargo registry, git, and target caches;
  - builds and packages the daemon;
  - runs daemon Rust tests before packaging;
  - does not publish to GitHub.
- Raspberry Pi board:
  - installs release assets through `mise`;
  - runs the daemon through systemd;
  - does not contain a source checkout.

### Daemon Runtime Config

The daemon searches for config in this order:

1. `--env-file`
2. `TXING_DAEMON_ENV_FILE`
3. `TXING_DAEMON_CONFIG_DIR/.env`
4. `XDG_CONFIG_HOME/txing/unit-daemon/.env`
5. `$HOME/.config/txing/unit-daemon/.env`

The standard config directory is:

```text
${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}
```

The macOS and board layouts are intentionally the same:

```text
~/.config/txing/unit-daemon/.env
~/.config/txing/unit-daemon/AmazonRootCA1.pem
~/.config/txing/unit-daemon/certificate.arn
~/.config/txing/unit-daemon/certificate.pem.crt
~/.config/txing/unit-daemon/private.pem.key
~/.config/txing/unit-daemon/public.pem.key
```

The `.env` file is directly sourceable and contains host-independent runtime
values:

```bash
export TXING_THING_ID=unit-bl95f2
export AWS_REGION=eu-central-1
export TXING_IOT_ENDPOINT=...
export TXING_IOT_CREDENTIAL_ENDPOINT=...
export TXING_IOT_ROLE_ALIAS=txing-daemon-unit-bl95f2
export TXING_CLOUDWATCH_LOG_GROUP=txing/<town>/<rig>/unit-bl95f2
export TXING_CLOUDWATCH_LOG_LEVEL=info
export TXING_CLOUDWATCH_LOG_RETENTION_DAYS=14
```

Certificate paths are not written into `.env` by default. When explicit cert
path variables are absent, the daemon loads `certificate.pem.crt`,
`private.pem.key`, and `AmazonRootCA1.pem` from the same directory as the loaded
`.env`.

### Local Development Commands

Provision daemon config and certificates only when AWS resource changes are
intended:

```bash
just unit::daemon::cert <thing-id>
```

The `cert` recipe creates or updates AWS IAM/IoT resources and refuses to
overwrite existing `.env` or certificate material.

Run the daemon from the macOS checkout after config exists:

```bash
just unit::daemon::run
```

That recipe runs:

```bash
cargo run --manifest-path devices/unit/daemon/Cargo.toml
```

### Feature Prerelease Artifact

The feature prerelease recipe builds a Linux `aarch64` archive:

```text
devices/unit/daemon/target/prerelease/txing-unit-daemon-linux-aarch64.tar.gz
```

The archive contains one root-level executable:

```text
txing-unit-daemon
```

Feature prerelease versions are generated from the next patch after root
`VERSION` plus a Unix timestamp:

```text
v<NEXT_PATCH>-feature.<unix_timestamp>
```

Example:

```text
v0.9.8-feature.1778793458
```

The publish step pushes the current commit to the moving branch
`feature/unit-daemon-prerelease`, creates the timestamped tag, publishes a
GitHub prerelease, uploads the archive asset, and keeps only the latest 10
matching unit-daemon feature prereleases.

### Stable Release Workflow

Stable daemon releases are built by:

```text
.github/workflows/unit-daemon-stable-release.yml
```

The workflow builds natively on `ubuntu-24.04-arm`, installs Rust `1.95.0`,
runs daemon tests, builds the release binary, strips it, and packages the same
mise-compatible archive used by feature prereleases:

```text
txing-unit-daemon-linux-aarch64.tar.gz
```

The archive contains one root-level executable:

```text
txing-unit-daemon
```

The stable tag and release name are exactly:

```text
v<VERSION>
```

The workflow is manual-only through `workflow_dispatch` and may run only from
`main`. It publishes a normal GitHub Release with `prerelease=false` and fails
if the stable tag or release already exists. It caches the Rust toolchain, Cargo
downloads, Cargo git checkouts, and `devices/unit/daemon/target` using cache
keys scoped to Rust `1.95.0` and `devices/unit/daemon/Cargo.lock`.

### Board Mise Config

The board uses one mise config path for both channels:

```text
/home/txing/.config/mise/txing-unit-daemon/config.toml
```

Feature channel:

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

Stable channel:

```toml
[tool_alias]
txing-unit-daemon = "github:mparkachov/txing"

[tools.txing-unit-daemon]
version = "latest"
asset_pattern = "txing-unit-daemon-linux-aarch64.tar.gz"
prerelease = false
```

Stable mode is installed by the same script. It installs the latest stable
release into the `txing` user's persistent mise install tree during the writable
maintenance window.

### Board Systemd Service

The installed service name is shared by both channels:

```text
txing-unit-daemon.service
```

The raw repository installer writes:

```text
/etc/systemd/system/txing-unit-daemon.service
/home/txing/.config/mise/txing-unit-daemon/config.toml
```

The service runs as the dedicated `txing` user. Stable mode uses the normal
persistent mise install tree:

```text
/home/txing/.local/share/mise/installs/txing-unit-daemon/
```

Feature mode stores boot-lifetime mise install, cache, and temp state under the
executable `/var/tmp` tmpfs:

```text
/var/tmp/txing/unit-daemon/mise
/var/tmp/txing/unit-daemon/mise-cache
/var/tmp/txing/unit-daemon/mise-tmp
```

The stable service uses this shape:

```ini
[Unit]
Description=Txing Unit Daemon
Wants=network-online.target systemd-time-wait-sync.service
After=network-online.target systemd-time-wait-sync.service time-sync.target

[Service]
Type=simple
User=txing
Group=txing
WorkingDirectory=/home/txing
KillSignal=SIGINT
TimeoutStartSec=180
TimeoutStopSec=30
Restart=on-failure
RestartSec=5

Environment=MISE_CONFIG_DIR=/home/txing/.config/mise/txing-unit-daemon
Environment=TXING_DAEMON_CONFIG_DIR=/home/txing/.config/txing/unit-daemon
Environment=HOME=/home/txing

ExecStart=/usr/bin/env MISE_OFFLINE=1 /home/txing/.local/bin/mise exec -- txing-unit-daemon

[Install]
WantedBy=multi-user.target
```

Feature mode additionally sets the `/var/tmp` mise directories, enables
prereleases, and installs at service start:

```ini
Environment=MISE_DATA_DIR=/var/tmp/txing/unit-daemon/mise
Environment=MISE_CACHE_DIR=/var/tmp/txing/unit-daemon/mise-cache
Environment=MISE_TMP_DIR=/var/tmp/txing/unit-daemon/mise-tmp
Environment=MISE_PRERELEASES=1

ExecStartPre=/usr/bin/install -d -m 700 /var/tmp/txing/unit-daemon/mise /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp
ExecStartPre=/home/txing/.local/bin/mise install
ExecStartPre=-/usr/bin/find /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp -mindepth 1 -maxdepth 1 -exec rm -rf {} +
```

The daemon startup log includes the selected version:

```text
info: starting unit daemon version=<version> ...
```

The clock-sync dependency is required because `mise install` performs HTTPS
requests before daemon startup. If the board has network but the clock still has
an old boot-time value, TLS certificate validation can fail with "certificate
not valid yet".

## Manual Steps Used To Complete Phase 1

These steps document the manual workflow used to prove phase 1 end to end.

### 1. Prepare The Docker Builder

Confirm macOS can reach the Lima Docker daemon and that it is native Linux
`arm64`:

```bash
docker run --rm alpine:latest uname -a
```

The Lima instance must mount the checkout path, for example:

```yaml
mounts:
  - location: "/Users/Maxim/Developer/txing"
    writable: true
```

Build the reusable prerelease builder image:

```bash
just unit::daemon::prerelease-builder-image
```

For manual debugging, open the cached builder environment:

```bash
just unit::daemon::prerelease-builder-shell
```

The shell mounts the repo read-only at `/Users/Maxim/Developer/txing`, mounts
Cargo cache volumes, and writes build artifacts to the target volume.

### 2. Provision Local Daemon Config On macOS

Run this only when certificate or AWS daemon resource provisioning is intended:

```bash
just unit::daemon::cert <thing-id>
```

Confirm the generated config:

```bash
ls -al "$HOME/.config/txing/unit-daemon"
```

### 3. Copy Config To The Board

From macOS:

```bash
test -r "$HOME/.config/txing/unit-daemon/.env"
test -r "$HOME/.config/txing/unit-daemon/private.pem.key"
COPYFILE_DISABLE=1 tar -C "$HOME/.config/txing" -czf /tmp/txing-unit-daemon-config.tgz unit-daemon
scp /tmp/txing-unit-daemon-config.tgz txing:/tmp/txing-unit-daemon-config.tgz
```

On the board as `txing`:

```bash
install -d -m 700 "$HOME/.config/txing"
tar -xzf /tmp/txing-unit-daemon-config.tgz -C "$HOME/.config/txing"
chmod 700 "$HOME/.config/txing/unit-daemon"
chmod 600 "$HOME/.config/txing/unit-daemon/.env"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.arn"
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.pem.crt"
chmod 600 "$HOME/.config/txing/unit-daemon/private.pem.key"
chmod 600 "$HOME/.config/txing/unit-daemon/public.pem.key"
chmod 644 "$HOME/.config/txing/unit-daemon/AmazonRootCA1.pem"
rm -f /tmp/txing-unit-daemon-config.tgz
```

### 4. Build The Feature Prerelease With Docker

From the macOS checkout:

```bash
just unit::daemon::prerelease-build
```

The build recipe requires:

- Docker connected to a native Linux `arm64` daemon;
- the `txing-unit-daemon-builder:ubuntu24-rust-stable` image built by
  `just unit::daemon::prerelease-builder-image`;
- a clean git worktree, including untracked files.

It runs daemon tests, builds the release binary, strips it, packages it, and
writes JSON metadata beside the staged archive. The repository bind mount is
read-only inside Docker; generated outputs are copied back into
`devices/unit/daemon/target/prerelease` by the host recipe.

### 5. Publish The Feature Prerelease From macOS

From the macOS checkout:

```bash
just unit::daemon::prerelease-publish
```

The publish recipe requires:

- macOS;
- authenticated `gh`;
- a clean git worktree;
- current `HEAD` matching the Docker build metadata.

It pushes `HEAD` to `feature/unit-daemon-prerelease`, pushes the timestamped
tag, creates the GitHub prerelease, uploads
`txing-unit-daemon-linux-aarch64.tar.gz`, and prunes older matching feature
prereleases beyond the latest 10.

### 6. Publish A Stable Release During Phase 2

Stable publishing is manual-only. After merging to `main`, run the
`Unit Daemon Stable Release` workflow manually from `main`.

The workflow reads root `VERSION`, creates release `v<VERSION>`, and rejects the
run if that stable tag or release already exists.

### 7. Install Or Update The Board Service

For feature-channel installs, confirm `/var/tmp` is writable and executable:

```bash
findmnt -no TARGET,FSTYPE,SIZE,AVAIL,OPTIONS /var/tmp
```

Expected shape on the Raspberry Pi Zero 2 W board:

```text
/var/tmp tmpfs 96M ... rw,nosuid,nodev,relatime,size=98304k
```

Enter writable-root maintenance mode:

```bash
root-rw
```

Install or switch to the feature channel:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/feature/unit-daemon-prerelease/devices/unit/daemon/install-systemd.sh | sudo bash -s -- feature
```

The same installer supports stable mode once stable release assets exist:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh | sudo bash -s -- stable
```

The installer validates Linux/systemd, the `txing` user, daemon runtime config,
root writability, and `mise`; for feature mode it also validates `/var/tmp`.
Then it enables `NetworkManager-wait-online.service` when present, writes the
mise config and systemd unit, reloads systemd, enables the service, and restarts
it.

Stable mode runs `mise install` once during the installer, as the `txing` user,
and stores the selected stable release under
`/home/txing/.local/share/mise/installs/txing-unit-daemon/`. The stable service
then starts offline without `ExecStartPre=mise install`, so it can run after the
root filesystem is switched back to read-only.

Feature mode keeps the boot-lifetime behavior: the service runs `mise install`
through `ExecStartPre`, stores the selected feature release under
`/var/tmp/txing/unit-daemon/mise`, and installs again after reboot because
`root-ro` clears `/var/tmp`.

To verify the currently installed release before switching back to read-only:

```bash
sudo journalctl -u txing-unit-daemon.service -n 120 --no-pager
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo -u txing env \
  MISE_CONFIG_DIR=/home/txing/.config/mise/txing-unit-daemon \
  HOME=/home/txing \
  /home/txing/.local/bin/mise list
sudo -u txing env \
  MISE_CONFIG_DIR=/home/txing/.config/mise/txing-unit-daemon \
  HOME=/home/txing \
  /home/txing/.local/bin/mise which txing-unit-daemon
```

### 8. Verify Before Reboot

Check the installed service:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -n 120 --no-pager
```

Confirm the journal shows:

- `mise install`;
- the selected `version=<version>` in the daemon startup log;
- MQTT connection;
- retained `board` capability publish.

### 9. Verify Read-Only Reboot

Return the board to read-only mode and reboot:

```bash
root-ro
sudo reboot
```

After reboot:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -n 120 --no-pager
```

The expected phase-1 result is that the service installs the selected mise
feature release into `/var/tmp`, starts offline through `mise exec`, logs the
feature version, and publishes the `board` capability without a source checkout
on the board.
