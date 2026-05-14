# Feature Mise Phase 1 Manual Implementation

This runbook documents the first phase-1 proof path from
[feature-mise.md](./feature-mise.md): compile the `unit` daemon in a Linux
`aarch64` builder, copy only the executable to the `txing` board, and run it in
the foreground from a temporary path.

These steps are intentionally manual. Do not turn them into an automatic deploy
or permanent board installation yet. Run each command at the prompt shown for
that host and stop after each command to inspect the output. Paste the output
back for review before continuing when a step needs confirmation.

## Scope

- Build on the Lima `txing` Linux `aarch64` VM.
- Do not build on the Raspberry Pi board.
- Do not copy a source checkout to the board.
- Publish GitHub prereleases only through the explicit macOS publish step; the
  Lima build step never talks to GitHub.
- Do not configure a permanent `mise` tool install or systemd unit on the board.
- Do not run `just unit::daemon::cert` as part of the build-only steps. That
  recipe creates or updates AWS resources and should be run only when
  deliberately provisioning daemon config and certificates.
- Keep CloudWatch logging in the generated `.env`; the foreground run may create
  or update CloudWatch Logs resources through the daemon's normal runtime path.

The foreground run still uses the daemon's normal AWS IoT runtime path. It may
read AWS IoT credentials and shadows and publish MQTT runtime state. Run it only
when those data-plane side effects are acceptable.

## Implemented Functionality

The phase-1 baseline now includes these implemented pieces:

- `just unit::daemon::cert <thing-id>` generates local daemon config under
  `${TXING_DAEMON_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/txing/unit-daemon}`.
- The generated config file is `.env`, uses sourceable `export KEY=value` lines,
  includes CloudWatch log settings, and lives beside the certificate files.
- The daemon can start without `--env-file` by loading the default `.env` from
  the per-user config directory.
- When `TXING_IOT_CERT_FILE`, `TXING_IOT_PRIVATE_KEY_FILE`, and
  `TXING_IOT_ROOT_CA_FILE` are absent, the daemon derives those paths from the
  loaded `.env` directory.
- `just unit::daemon::run` starts the daemon from the macOS checkout with:
  `cargo run --manifest-path devices/unit/daemon/Cargo.toml`.
- A macOS run through `just unit::daemon::run` has been confirmed to start and
  publish the `board` runtime capability state; the web UI then shows the board
  capability as enabled.
- `release::bump` and `release::check` now include
  `devices/unit/daemon/Cargo.toml` and the daemon package entry in
  `devices/unit/daemon/Cargo.lock`.
- `just unit::daemon::prerelease-build` runs in the Linux `aarch64` Lima builder,
  requires a clean worktree, runs daemon tests, builds the release binary, and
  stages `txing-unit-daemon-linux-aarch64.tar.gz` plus JSON metadata under
  `devices/unit/daemon/target/prerelease`. The archive contains a stripped
  root-level executable named `txing-unit-daemon`.
- `just unit::daemon::prerelease-publish` runs on macOS, requires `gh`, verifies
  the staged metadata against the current clean `HEAD`, pushes
  `feature/unit-daemon-prerelease`, creates
  `v<NEXT_PATCH>-feature.<unix_timestamp>`, publishes the GitHub prerelease, and
  keeps only the latest 10 matching unit-daemon feature prereleases.

For normal local development on macOS after config has been provisioned:

```bash
just unit::daemon::run
```

Provision or replace cert material only when AWS resource changes are intended:

```bash
just unit::daemon::cert unit-bl95f2
```

The `cert` recipe refuses to overwrite an existing `.env` or certificate files.
Move old material out of the config directory before intentionally issuing a
replacement certificate.

## Phase 1 GitHub Prerelease Flow

The prerelease flow is intentionally split across two hosts. Build in Lima:

```bash
limactl shell txing
```

If `just` is not on `PATH` but `mise exec -- just --version` works, activate mise
for future Lima login shells:

```bash
cat >> ~/.bashrc <<'EOF'
export PATH="$HOME/.local/bin:$PATH"
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
fi
EOF
```

```bash
exec bash
```

For the current shell before reloading `.bashrc`, use
`mise exec -- just unit::daemon::prerelease-build` instead of bare `just`.

```bash
cd /Users/Maxim/Developer/txing
```

```bash
just unit::daemon::prerelease-build
```

Current-shell fallback:

```bash
mise exec -- just unit::daemon::prerelease-build
```

Return to macOS:

```bash
exit
```

Publish from macOS:

```bash
just unit::daemon::prerelease-publish
```

Requirements:

- The git worktree must be clean for both steps, including untracked files.
- Dirty or untracked work must be committed before building or publishing.
- The publish step uses macOS `gh` authentication; the Lima builder does not need
  GitHub authentication.
- The default moving branch is `feature/unit-daemon-prerelease`.
- The tag and release name are `v<NEXT_PATCH>-feature.<unix_timestamp>`.
- The uploaded release asset is `txing-unit-daemon-linux-aarch64.tar.gz`.
  It contains a stripped root-level executable named `txing-unit-daemon`.
- The publish step prunes older matching unit-daemon feature prereleases beyond
  the latest 10, including their tags.

## Phase 1 Board Feature Install Smoke Test

After publishing a feature prerelease, configure the board to install that exact
version with mise from GitHub Releases. This step still does not copy a source
checkout to the board.

After publishing the new archive prerelease, set the feature version to the
version printed by `just unit::daemon::prerelease-build`:

```bash
feature_version="0.9.8-feature.<unix_timestamp>"
```

Log in to the board:

```bash
ssh txing
```

Create the phase-1 feature mise config on the board as the `txing` user:

```text
/home/txing/.config/mise/txing-unit-daemon-feature/config.toml
```

```bash
install -d -m 700 "$HOME/.config/mise/txing-unit-daemon-feature"
```

```bash
cat > "$HOME/.config/mise/txing-unit-daemon-feature/config.toml" <<EOF
[tool_alias]
txing-unit-daemon = "github:mparkachov/txing"

[tools.txing-unit-daemon]
version = "$feature_version"
asset_pattern = "txing-unit-daemon-linux-aarch64.tar.gz"
prerelease = true

[settings.github]
slsa = false
github_attestations = false
EOF
```

The GitHub verification settings are disabled only for this manual phase-1
feature channel. The asset was built locally in Lima and uploaded by `gh`, so it
does not have SLSA provenance or GitHub artifact attestations for mise to verify.
The `tool_alias` makes `mise list` report the tool as `txing-unit-daemon` while
still installing from the GitHub release backend.

Use the existing `/var/tmp` tmpfs for feature-channel mise install/cache/tmp
state. `/tmp` is intentionally small and already carries board runtime state, so
do not consume it for downloaded daemon artifacts. `/var/tmp` must be large
enough and executable; the read-only provisioning should mount it with
`size=96M` and explicit `exec`. The size is a tmpfs cap, not preallocated
memory, but the Raspberry Pi Zero 2 W has only 512 MB RAM, so keep the cap
tight and remove download/tmp cache after install.

```bash
findmnt -no TARGET,FSTYPE,SIZE,AVAIL,OPTIONS /var/tmp
```

```bash
df -h /var/tmp
```

If `/var/tmp` is still the old 16M mount or shows `noexec`, remount it for this
manual test:

```bash
sudo mount -o remount,rw,exec,nosuid,nodev,mode=1777,size=96M /var/tmp
```

```bash
findmnt -no TARGET,FSTYPE,SIZE,AVAIL,OPTIONS /var/tmp
```

Create the mise directories as the `txing` user:

```bash
install -d -m 700 /var/tmp/txing/unit-daemon/mise /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp
```

Export the same environment shape the future feature service will use:

```bash
export MISE_CONFIG_DIR="$HOME/.config/mise/txing-unit-daemon-feature"
```

```bash
export MISE_DATA_DIR=/var/tmp/txing/unit-daemon/mise
```

```bash
export MISE_CACHE_DIR=/var/tmp/txing/unit-daemon/mise-cache
```

```bash
export MISE_TMP_DIR=/var/tmp/txing/unit-daemon/mise-tmp
```

```bash
export MISE_PRERELEASES=1
```

```bash
export TXING_DAEMON_CONFIG_DIR="$HOME/.config/txing/unit-daemon"
```

Install the feature binary into the `/var/tmp` tmpfs:

```bash
mise install
```

Inspect and then remove mise download/tmp cache. `mise exec --offline` only
needs the installed tool in `MISE_DATA_DIR`.

```bash
du -sh /var/tmp/txing/unit-daemon/*
```

```bash
rm -rf /var/tmp/txing/unit-daemon/mise-cache/* /var/tmp/txing/unit-daemon/mise-tmp/*
```

Confirm that mise resolves the command from the `/var/tmp` install:

```bash
mise which txing-unit-daemon
```

Expected path shape:

```text
/var/tmp/txing/unit-daemon/mise/installs/txing-unit-daemon/<feature-version>/...
```

Verify the binary without starting the daemon:

```bash
MISE_OFFLINE=1 mise exec -- txing-unit-daemon --help >/dev/null
```

If the board does not already have daemon runtime config, copy the generated
macOS config directory to the board before starting the daemon. Run these
commands on macOS:

```bash
test -r "$HOME/.config/txing/unit-daemon/.env"
```

```bash
test -r "$HOME/.config/txing/unit-daemon/private.pem.key"
```

```bash
COPYFILE_DISABLE=1 tar -C "$HOME/.config/txing" -czf /tmp/txing-unit-daemon-config.tgz unit-daemon
```

```bash
tar -tzf /tmp/txing-unit-daemon-config.tgz
```

```bash
scp /tmp/txing-unit-daemon-config.tgz txing:/tmp/txing-unit-daemon-config.tgz
```

Then on the board as the `txing` user:

```bash
install -d -m 700 "$HOME/.config/txing"
```

```bash
tar -xzf /tmp/txing-unit-daemon-config.tgz -C "$HOME/.config/txing"
```

```bash
chmod 700 "$HOME/.config/txing/unit-daemon"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/.env"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.arn"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.pem.crt"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/private.pem.key"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/public.pem.key"
```

```bash
chmod 644 "$HOME/.config/txing/unit-daemon/AmazonRootCA1.pem"
```

```bash
rm -f /tmp/txing-unit-daemon-config.tgz
```

```bash
test -r "$HOME/.config/txing/unit-daemon/.env"
```

```bash
test -r "$HOME/.config/txing/unit-daemon/private.pem.key"
```

Run the feature binary in the foreground for the same 90-second smoke window:

```bash
timeout --signal INT 90s env MISE_OFFLINE=1 mise exec -- txing-unit-daemon
```

The first daemon log line should include the exact feature version, for example:

```text
info: starting unit daemon version=0.9.8-feature.<unix_timestamp> ...
```

If `timeout` exits with status `124`, that is the expected timeout status for a
successful foreground smoke test. Any other nonzero status needs investigation.

## Phase 1 Systemd Feature Service Smoke Test

After the foreground smoke test passes, test the same flow through systemd. This
strict phase-1 unit performs a fresh `mise install` during service start, removes
mise download/tmp cache, then starts the daemon offline. If install fails, service
start should fail visibly.

Stay logged in to the board as the `txing` user and resolve the installed mise
path:

```bash
mise_bin="$(command -v mise)"
```

```bash
test -x "$mise_bin"
```

```bash
printf '%s\n' "$mise_bin"
```

Confirm `/var/tmp` is still the 96M executable tmpfs:

```bash
findmnt -no TARGET,FSTYPE,SIZE,AVAIL,OPTIONS /var/tmp
```

Creating the unit writes to `/etc/systemd/system`. If the root filesystem is
currently read-only, enter the existing writable maintenance mode first:

```bash
root-rw
```

Create the test systemd unit:

```bash
sudo tee /etc/systemd/system/txing-unit-daemon-feature.service >/dev/null <<EOF
[Unit]
Description=Txing Unit Daemon Feature Channel
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

Environment=MISE_CONFIG_DIR=/home/txing/.config/mise/txing-unit-daemon-feature
Environment=MISE_DATA_DIR=/var/tmp/txing/unit-daemon/mise
Environment=MISE_CACHE_DIR=/var/tmp/txing/unit-daemon/mise-cache
Environment=MISE_TMP_DIR=/var/tmp/txing/unit-daemon/mise-tmp
Environment=MISE_PRERELEASES=1
Environment=TXING_DAEMON_CONFIG_DIR=/home/txing/.config/txing/unit-daemon
Environment=HOME=/home/txing

ExecStartPre=/usr/bin/install -d -m 700 /var/tmp/txing/unit-daemon/mise /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp
ExecStartPre=$mise_bin install
ExecStartPre=-/usr/bin/find /var/tmp/txing/unit-daemon/mise-cache /var/tmp/txing/unit-daemon/mise-tmp -mindepth 1 -maxdepth 1 -exec rm -rf {} +
ExecStart=/usr/bin/env MISE_OFFLINE=1 $mise_bin exec -- txing-unit-daemon

[Install]
WantedBy=multi-user.target
EOF
```

Load the unit:

```bash
sudo systemctl daemon-reload
```

Force a fresh feature-channel install by clearing only the tmpfs-backed daemon
mise state:

```bash
sudo systemctl stop txing-unit-daemon-feature.service 2>/dev/null || true
```

```bash
sudo rm -rf /var/tmp/txing/unit-daemon
```

Start the service:

```bash
sudo systemctl start txing-unit-daemon-feature.service
```

Inspect the installed executable and journal:

```bash
mise which txing-unit-daemon
```

```bash
ls -alh "$(mise which txing-unit-daemon)"
```

```bash
du -sh /var/tmp/txing/unit-daemon/*
```

```bash
sudo systemctl status --no-pager -l txing-unit-daemon-feature.service
```

```bash
sudo journalctl -u txing-unit-daemon-feature.service -n 120 --no-pager
```

The first daemon startup line in the journal should include
`version=<feature-version>`.

Stop the service and confirm the daemon publishes offline state:

```bash
sudo systemctl stop txing-unit-daemon-feature.service
```

```bash
sudo journalctl -u txing-unit-daemon-feature.service -n 80 --no-pager
```

Keep the unit installed only if this board should continue running the feature
channel service. Otherwise remove the test unit:

```bash
sudo systemctl disable --now txing-unit-daemon-feature.service
```

```bash
sudo rm -f /etc/systemd/system/txing-unit-daemon-feature.service
```

```bash
sudo systemctl daemon-reload
```

Return to macOS after collecting output:

```bash
exit
```

## 1. Confirm Host Access

From the macOS repository checkout, run each command separately:

```bash
uname -a
```

```bash
pwd
```

```bash
just --version
```

Log in to the Raspberry Pi board:

```bash
ssh txing
```

On the board, run each command separately:

```bash
uname -a
```

```bash
pwd
```

```bash
mise --version
```

```bash
mise exec -- just --version
```

Return to macOS:

```bash
exit
```

Log in to the Lima builder:

```bash
limactl shell txing
```

In the Lima builder, run each command separately:

```bash
uname -a
```

```bash
pwd
```

```bash
mise --version
```

```bash
mise exec -- just --version
```

Return to macOS:

```bash
exit
```

Expected shape:

- macOS developer host is `arm64`.
- `ssh txing` reaches the Raspberry Pi board as the `txing` user.
- `limactl shell txing` reaches a Linux `aarch64` VM with the repository mounted
  at `/Users/Maxim/Developer/txing`.
- `just` is available through `mise` on both Linux hosts.

## 2. Provision The Lima Builder

The Lima VM needs native Linux build tools and Rust. Log in to the Lima builder:

```bash
limactl shell txing
```

In the Lima builder, run each command separately:

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y build-essential pkg-config cmake perl git
```

```bash
mise use --global rust@1.95.0
```

```bash
mise exec -- rustc -vV
```

Enable mise activation for future Lima login shells so `just` and `cargo` can be
run directly:

```bash
cat >> ~/.bashrc <<'EOF'
export PATH="$HOME/.local/bin:$PATH"
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
fi
EOF
```

```bash
exec bash
```

Verify direct `just` lookup after reloading the shell:

```bash
just --version
```

If a previous apt run was interrupted, repair the VM manually before retrying:

```bash
sudo dpkg --configure -a
```

```bash
sudo apt-get install -f
```

The final `rustc -vV` output should report Rust `1.95.0` for an `aarch64`
Linux host. Return to macOS when this step is complete:

```bash
exit
```

## 3. Run Daemon Tests In Lima

Log in to the Lima builder:

```bash
limactl shell txing
```

In the Lima builder, run:

```bash
cd /Users/Maxim/Developer/txing
```

Run the daemon tests before creating the manual artifact:

```bash
mise exec -- cargo test --manifest-path devices/unit/daemon/Cargo.toml
```

Expected result: all `txing-unit-daemon` tests pass.

## 4. Build The Release Binary In Lima

Stay in the Lima builder or log in again with `limactl shell txing`. In the Lima
builder, run:

```bash
cd /Users/Maxim/Developer/txing
```

Build only the daemon binary target:

```bash
mise exec -- cargo build --release --manifest-path devices/unit/daemon/Cargo.toml --bin daemon
```

Inspect the resulting executable:

```bash
file devices/unit/daemon/target/release/daemon
```

```bash
ldd devices/unit/daemon/target/release/daemon
```

Expected result:

- `file` reports a Linux `aarch64` ELF executable.
- `ldd` resolves the dynamic libraries instead of reporting missing
  dependencies.
- `not stripped` in the `file` output is acceptable for this manual phase-1
  proof.
- A minimal dynamic dependency set of `libgcc_s`, `libm`, `libc`, and
  `/lib/ld-linux-aarch64.so.1` is acceptable.

The current Cargo binary target is named `daemon`; the future installed command
name in `feature-mise.md` is `txing-unit-daemon`. For this phase-1 manual test,
copy and install the built `daemon` executable under the future command name on
the board. Return to macOS when the build has been inspected:

```bash
exit
```

## 5. Copy Only The Binary To The Board

From macOS, copy the built executable to a temporary board path:

```bash
scp /Users/Maxim/Developer/txing/devices/unit/daemon/target/release/daemon txing:/tmp/txing-unit-daemon.manual
```

Do not copy the repository checkout or Cargo build directory to the board.

## 6. Run A Foreground Smoke Test On The Board

The daemon now expects its config and certificate material in a colocated
per-user config directory:

```text
$HOME/.config/txing/unit-daemon/
```

The directory contains:

```text
.env
AmazonRootCA1.pem
certificate.arn
certificate.pem.crt
private.pem.key
public.pem.key
```

The `.env` file is directly sourceable and should contain host-independent
runtime values only:

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

The daemon derives the colocated cert paths from the loaded `.env` path, so the
same directory can be copied between macOS and the board without editing `.env`.
The CloudWatch log stream is intentionally omitted; the daemon defaults it to a
per-client stream derived from the generated client ID.

If the config was generated on macOS with `just unit::daemon::cert`, copy it to
the board from macOS:

```bash
cd "$HOME/.config/txing"
```

```bash
COPYFILE_DISABLE=1 tar -czf /tmp/txing-unit-daemon-config.tgz unit-daemon
```

```bash
tar -tzf /tmp/txing-unit-daemon-config.tgz
```

Expected archive entries:

```text
unit-daemon/
unit-daemon/.env
unit-daemon/AmazonRootCA1.pem
unit-daemon/certificate.arn
unit-daemon/certificate.pem.crt
unit-daemon/private.pem.key
unit-daemon/public.pem.key
```

Copy the archive to the board:

```bash
scp /tmp/txing-unit-daemon-config.tgz txing:/tmp/txing-unit-daemon-config.tgz
```

Log in to the board:

```bash
ssh txing
```

On the board, inspect and unpack the archive:

```bash
tar -tzf /tmp/txing-unit-daemon-config.tgz
```

```bash
install -d -m 700 "$HOME/.config/txing"
```

```bash
tar -xzf /tmp/txing-unit-daemon-config.tgz -C "$HOME/.config/txing"
```

Apply the expected permissions:

```bash
chmod 700 "$HOME/.config/txing/unit-daemon"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/.env"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.arn"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/certificate.pem.crt"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/private.pem.key"
```

```bash
chmod 600 "$HOME/.config/txing/unit-daemon/public.pem.key"
```

```bash
chmod 644 "$HOME/.config/txing/unit-daemon/AmazonRootCA1.pem"
```

Verify the config and cert files:

```bash
find "$HOME/.config/txing/unit-daemon" -maxdepth 1 -type f -exec ls -l {} \;
```

Expected permissions:

- `$HOME/.config/txing/unit-daemon/.env`: mode `600`.
- `$HOME/.config/txing/unit-daemon/private.pem.key`: mode `600`.
- `$HOME/.config/txing/unit-daemon/AmazonRootCA1.pem`: mode `644`.
- Other cert metadata and public/certificate files: mode `600`.

Confirm the daemon can find its config:

```bash
test -r "$HOME/.config/txing/unit-daemon/.env"
```

```bash
test -r "$HOME/.config/txing/unit-daemon/private.pem.key"
```

```bash
. "$HOME/.config/txing/unit-daemon/.env"
```

Remove the temporary config archive from the board:

```bash
rm -f /tmp/txing-unit-daemon-config.tgz
```

On the board, run each smoke-test setup command separately. These commands
create a temporary runtime directory and verify `--help`.

```bash
manual_dir="${XDG_RUNTIME_DIR:-/tmp}/txing-daemon-manual"
```

```bash
rm -rf "$manual_dir"
```

```bash
install -d -m 700 "$manual_dir"
```

```bash
install -m 700 /tmp/txing-unit-daemon.manual "$manual_dir/txing-unit-daemon"
```

```bash
"$manual_dir/txing-unit-daemon" --help >/dev/null
```

Run the foreground smoke test for 90 seconds:

```bash
timeout --signal INT 90s "$manual_dir/txing-unit-daemon"
```

If `timeout` exits with status `124`, that is the expected timeout status for a
successful foreground smoke test. Any other nonzero status needs investigation
before continuing.

Return to macOS only after collecting the daemon output:

```bash
exit
```

Back on macOS, remove the temporary config archive:

```bash
rm -f /tmp/txing-unit-daemon-config.tgz
```

Expected result:

- `--help` exits successfully.
- The daemon starts, reads the sparkplug shadow, connects to MQTT, publishes its
  runtime state, and exits when `timeout` sends `SIGINT`.
- Exit status `124` from `timeout` is acceptable.
- Any other nonzero exit status needs investigation before continuing.

## 7. Manual Cleanup Checks

Clean up the temporary board files after the smoke test. Log in to the board if
needed with `ssh txing`, then run:

```bash
rm -f /tmp/txing-unit-daemon.manual
```

```bash
rm -rf "${XDG_RUNTIME_DIR:-/tmp}/txing-daemon-manual"
```

Return to macOS:

```bash
exit
```

The build artifact remains in the local checkout under:

```text
devices/unit/daemon/target/release/daemon
```

Remove it only if a clean rebuild is desired.

## 8. Record The Result

After the manual run, record:

- Whether `just unit::daemon::run` starts the daemon on macOS with the generated
  per-user config.
- Whether the web UI shows the `board` capability as enabled while the daemon is
  running.
- Lima `rustc -vV` output.
- Test result from `cargo test`.
- `file` and `ldd` output for the release binary.
- Whether the board `--help` check passed.
- Whether the 90-second foreground run exited with status `124` or another
  status.
- Any daemon log lines showing startup, shadow read, MQTT publish, shutdown, or
  errors.

This record is the evidence for whether phase 1 can move from a manual binary
copy to the next release/mise implementation step.
