# Feature Mise Phase 1 Implementation

This runbook documents the current phase-1 path from
[feature-mise.md](./feature-mise.md): build the `unit` daemon in a Linux
`aarch64` builder, publish a feature prerelease from macOS, and install the
board systemd service through a raw repository installer script.

The board installer is intentionally explicit and local to one board. It does
not copy a source checkout to the board, does not provision certificates, and
does not run AWS provisioning commands.

## Scope

- Build on the Lima `txing` Linux `aarch64` VM.
- Do not build on the Raspberry Pi board.
- Do not copy a source checkout to the board.
- Publish GitHub prereleases only through the explicit macOS publish step; the
  Lima build step never talks to GitHub.
- Do not run `just unit::daemon::cert` as part of the build-only steps. That
  recipe creates or updates AWS resources and should be run only when
  deliberately provisioning daemon config and certificates.
- Keep CloudWatch logging in the generated `.env`; the daemon service may create
  or update CloudWatch Logs resources through the daemon's normal runtime path.

## Implemented Functionality

The phase-1 baseline now includes these pieces:

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
- `release::bump` and `release::check` include `devices/unit/daemon/Cargo.toml`
  and the daemon package entry in `devices/unit/daemon/Cargo.lock`.
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
- `devices/unit/daemon/install-systemd.sh` installs or updates the generic
  `txing-unit-daemon.service` systemd unit and the generic
  `/home/txing/.config/mise/txing-unit-daemon/config.toml` mise config for either
  `feature` or `stable` channel mode.

For normal local development on macOS after config has been provisioned:

```bash
just unit::daemon::run
```

Provision or replace cert material only when AWS resource changes are intended:

```bash
just unit::daemon::cert <thing-id>
```

The `cert` recipe refuses to overwrite an existing `.env` or certificate files.
Move old material out of the config directory before intentionally issuing a
replacement certificate.

## Phase 1 GitHub Prerelease Flow

The prerelease flow is split across two hosts. Build in Lima:

```bash
limactl shell txing
```

If `mise` itself is missing, install it first:

```bash
curl https://mise.run | sh
```

```bash
export PATH="$HOME/.local/bin:$PATH"
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

## Phase 1 Board Systemd Install

After publishing a feature prerelease, install or update the board service with
the raw repository installer. This step does not copy a source checkout to the
board.

The board must already have daemon runtime config and certificate material:

```text
/home/txing/.config/txing/unit-daemon/.env
/home/txing/.config/txing/unit-daemon/private.pem.key
```

If the board does not have that directory yet, copy the generated macOS config
directory first. Run these commands on macOS:

```bash
test -r "$HOME/.config/txing/unit-daemon/.env"
test -r "$HOME/.config/txing/unit-daemon/private.pem.key"
COPYFILE_DISABLE=1 tar -C "$HOME/.config/txing" -czf /tmp/txing-unit-daemon-config.tgz unit-daemon
scp /tmp/txing-unit-daemon-config.tgz txing:/tmp/txing-unit-daemon-config.tgz
```

Then on the board as the `txing` user:

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

Confirm `/var/tmp` is the executable tmpfs from the read-only-root provisioning:

```bash
findmnt -no TARGET,FSTYPE,SIZE,AVAIL,OPTIONS /var/tmp
```

Expected shape:

```text
/var/tmp tmpfs 96M ... rw,nosuid,nodev,relatime,size=98304k
```

If root is currently read-only, enter the existing writable maintenance mode:

```bash
root-rw
```

Install or switch to the feature channel with the raw script from the moving
feature branch:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/feature/unit-daemon-prerelease/devices/unit/daemon/install-systemd.sh | sudo bash -s -- feature
```

The same script supports the stable channel once stable daemon release assets
exist:

```bash
curl -fsSL https://raw.githubusercontent.com/mparkachov/txing/main/devices/unit/daemon/install-systemd.sh | sudo bash -s -- stable
```

Both modes write the same service and config paths:

```text
/etc/systemd/system/txing-unit-daemon.service
/home/txing/.config/mise/txing-unit-daemon/config.toml
```

The installer runs:

```bash
sudo systemctl daemon-reload
sudo systemctl enable txing-unit-daemon.service
sudo systemctl restart txing-unit-daemon.service
```

Inspect the service:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -n 120 --no-pager
```

The first daemon startup line in the journal should include the selected daemon
version:

```text
info: starting unit daemon version=<version> ...
```

After feature install succeeds, return the board to read-only mode and reboot to
verify boot-time install/start:

```bash
root-ro
sudo reboot
```

After reboot:

```bash
sudo systemctl status --no-pager -l txing-unit-daemon.service
sudo journalctl -u txing-unit-daemon.service -n 120 --no-pager
```
