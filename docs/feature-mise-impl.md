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
  - publishes GitHub prereleases through authenticated `gh`.
- Lima Linux `aarch64` builder:
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

The workflow publishes a normal GitHub Release with `prerelease=false` and fails
if the stable tag or release already exists. It caches the Rust toolchain, Cargo
downloads, Cargo git checkouts, and `devices/unit/daemon/target` using cache
keys scoped to Rust `1.95.0` and `devices/unit/daemon/Cargo.lock`.

Final behavior is stable publishing from `main`. During phase-2 development, the
workflow also supports a temporary tag-push path from
`feature/build-daemon-for-txing`: the pushed tag must match root `VERSION`, and
the tagged commit must be reachable from that feature branch.

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

Stable mode is installed by the same script, but stable release publishing is a
phase-2 task. Until stable daemon release assets exist, feature mode is the
validated phase-1 path.

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

The service runs as the dedicated `txing` user. It stores boot-lifetime mise
install, cache, and temp state under the executable `/var/tmp` tmpfs:

```text
/var/tmp/txing/unit-daemon/mise
/var/tmp/txing/unit-daemon/mise-cache
/var/tmp/txing/unit-daemon/mise-tmp
```

The service uses this shape:

```ini
[Unit]
Description=Txing Unit Daemon
Wants=network-online.target
After=network-online.target

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
Environment=MISE_DATA_DIR=/var/tmp/txing/unit-daemon/mise
Environment=MISE_CACHE_DIR=/var/tmp/txing/unit-daemon/mise-cache
Environment=MISE_TMP_DIR=/var/tmp/txing/unit-daemon/mise-tmp
Environment=TXING_DAEMON_CONFIG_DIR=/home/txing/.config/txing/unit-daemon
Environment=HOME=/home/txing

ExecStartPre=/usr/bin/install -d -m 700 /var/tmp/txing/unit-daemon/mise /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp
ExecStartPre=/home/txing/.local/bin/mise install
ExecStartPre=-/usr/bin/find /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp -mindepth 1 -maxdepth 1 -exec rm -rf {} +
ExecStart=/usr/bin/env MISE_OFFLINE=1 /home/txing/.local/bin/mise exec -- txing-unit-daemon

[Install]
WantedBy=multi-user.target
```

Feature mode additionally sets:

```ini
Environment=MISE_PRERELEASES=1
```

The daemon startup log includes the selected version:

```text
info: starting unit daemon version=<version> ...
```

## Manual Steps Used To Complete Phase 1

These steps document the manual workflow used to prove phase 1 end to end.

### 1. Prepare The Lima Builder

Log in to the Lima builder:

```bash
limactl shell txing
```

Install `mise` if it is missing:

```bash
curl https://mise.run | sh
```

Add `mise` to the current shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Install Linux build dependencies once:

```bash
sudo apt-get update
sudo apt-get install -y build-essential pkg-config cmake perl git file python3
```

Install Rust and confirm tooling:

```bash
mise use --global rust@1.95.0
mise exec -- rustc -vV
mise exec -- just --version
```

Activate `mise` for future Lima login shells:

```bash
cat >> ~/.bashrc <<'EOF'
export PATH="$HOME/.local/bin:$PATH"
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
fi
EOF
exec bash
```

Before the shell has been reloaded, use `mise exec -- just ...` instead of bare
`just`.

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

### 4. Build The Feature Prerelease In Lima

Log in to Lima and run the build manually:

```bash
limactl shell txing
cd /Users/Maxim/Developer/txing
just unit::daemon::prerelease-build
exit
```

Current-shell fallback before `mise` activation:

```bash
mise exec -- just unit::daemon::prerelease-build
```

The build recipe requires:

- Linux `aarch64`;
- `cargo`, `file`, `git`, `python3`, `strip`, and `tar`;
- a clean git worktree, including untracked files.

It runs daemon tests, builds the release binary, strips it, packages it, and
writes JSON metadata beside the staged archive.

### 5. Publish The Feature Prerelease From macOS

From the macOS checkout:

```bash
just unit::daemon::prerelease-publish
```

The publish recipe requires:

- macOS;
- authenticated `gh`;
- a clean git worktree;
- current `HEAD` matching the Lima build metadata.

It pushes `HEAD` to `feature/unit-daemon-prerelease`, pushes the timestamped
tag, creates the GitHub prerelease, uploads
`txing-unit-daemon-linux-aarch64.tar.gz`, and prunes older matching feature
prereleases beyond the latest 10.

### 6. Publish A Stable Release During Phase 2

Temporary phase-2 stable publishing from this feature branch uses a matching
stable tag. From macOS, after committing the workflow and versioned daemon
changes:

```bash
version="$(tr -d '[:space:]' < VERSION)"
git tag "v$version"
git push origin "v$version"
```

The workflow rejects the tag unless it is exactly `v<VERSION>` and points to a
commit reachable from `origin/feature/build-daemon-for-txing`.

After the workflow exists on `main`, normal stable publishing is a push to
`main` with relevant changes. In both paths, an existing `v<VERSION>` release or
tag is treated as immutable and causes the workflow to fail.

### 7. Install Or Update The Board Service

Confirm `/var/tmp` is writable and executable:

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
`/var/tmp`, root writability, and `mise`; then it writes the mise config and
systemd unit, reloads systemd, enables the service, and restarts it.

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
