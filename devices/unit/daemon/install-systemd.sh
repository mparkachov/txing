#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: sudo bash install-systemd.sh stable|feature

Installs or updates the txing unit daemon systemd service for the selected mise
channel. Run this during a writable-root maintenance window.
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

channel="$1"
case "$channel" in
  stable|feature) ;;
  *)
    usage
    exit 2
    ;;
esac

if [ "$(id -u)" -ne 0 ]; then
  fail "this installer must run as root"
fi
if [ "$(uname -s)" != "Linux" ]; then
  fail "this installer must run on Linux"
fi
command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
[ -d /run/systemd/system ] || fail "systemd does not appear to be PID 1"

daemon_user="txing"
daemon_home="/home/$daemon_user"
daemon_group="$(id -gn "$daemon_user" 2>/dev/null)" || fail "user '$daemon_user' does not exist"
[ -d "$daemon_home" ] || fail "expected daemon home directory $daemon_home"

daemon_config_dir="$daemon_home/.config/txing/unit-daemon"
[ -r "$daemon_config_dir/.env" ] || fail "missing daemon runtime config: $daemon_config_dir/.env"
[ -r "$daemon_config_dir/private.pem.key" ] || fail "missing daemon private key: $daemon_config_dir/private.pem.key"

root_options="$(findmnt -no OPTIONS / 2>/dev/null || true)"
case ",$root_options," in
  *,ro,*) fail "root filesystem is read-only; run root-rw before installing the service" ;;
esac

systemd_dir="/etc/systemd/system"
[ -d "$systemd_dir" ] || fail "missing systemd unit directory: $systemd_dir"
write_probe="$systemd_dir/.txing-unit-daemon-write-test.$$"
if ! : >"$write_probe" 2>/dev/null; then
  fail "$systemd_dir is not writable; run root-rw before installing the service"
fi
rm -f "$write_probe"

resolve_mise() {
  if [ -x "$daemon_home/.local/bin/mise" ]; then
    printf '%s\n' "$daemon_home/.local/bin/mise"
    return 0
  fi
  if command -v runuser >/dev/null 2>&1; then
    user_mise="$(runuser -u "$daemon_user" -- sh -lc 'command -v mise' 2>/dev/null || true)"
    if [ -n "$user_mise" ] && [ -x "$user_mise" ]; then
      printf '%s\n' "$user_mise"
      return 0
    fi
  fi
  root_mise="$(command -v mise 2>/dev/null || true)"
  if [ -n "$root_mise" ] && [ -x "$root_mise" ]; then
    printf '%s\n' "$root_mise"
    return 0
  fi
  return 1
}

mise_bin="$(resolve_mise)" || fail "mise is required; install it for the '$daemon_user' user first"

mise_config_dir="$daemon_home/.config/mise/txing-unit-daemon"
mise_config_file="$mise_config_dir/config.toml"
stable_config_file="$daemon_home/.config/mise/conf.d/txing-unit-daemon.toml"
service_name="txing-unit-daemon.service"
service_file="$systemd_dir/$service_name"
legacy_service_name="txing-unit-daemon-feature.service"
legacy_service_file="$systemd_dir/$legacy_service_name"
tmp_root="/var/tmp/txing/unit-daemon"
asset_pattern="txing-unit-daemon-linux-aarch64.tar.gz"
stable_install_root="$daemon_home/.local/share/mise/installs/txing-unit-daemon"
var_tmp_probe=""

if [ "$channel" = "feature" ]; then
  [ -r "$stable_config_file" ] || fail "missing stable daemon mise config: $stable_config_file; install stable channel first"
  stable_binary_found=false
  for stable_binary in "$stable_install_root"/*/txing-unit-daemon; do
    if [ -x "$stable_binary" ]; then
      stable_binary_found=true
      break
    fi
  done
  [ "$stable_binary_found" = true ] || fail "missing persistent stable daemon install under $stable_install_root; install stable channel first"
  [ -d /var/tmp ] || fail "/var/tmp does not exist"
  [ -w /var/tmp ] || fail "/var/tmp is not writable"
  var_tmp_probe="$(mktemp -d /var/tmp/txing-unit-daemon-install.XXXXXX)"
  printf '#!/usr/bin/env sh\nexit 0\n' >"$var_tmp_probe/exec-test"
  chmod 700 "$var_tmp_probe/exec-test"
  "$var_tmp_probe/exec-test" >/dev/null 2>&1 || fail "/var/tmp must be mounted executable, without noexec"
fi

if systemctl list-unit-files NetworkManager-wait-online.service --no-legend --no-pager 2>/dev/null \
  | grep -q '^NetworkManager-wait-online\.service[[:space:]]'; then
  systemctl enable NetworkManager-wait-online.service >/dev/null
fi

install -d -m 700 -o "$daemon_user" -g "$daemon_group" "$daemon_home/.config/mise"
if [ "$channel" = "stable" ]; then
  install -d -m 700 -o "$daemon_user" -g "$daemon_group" "$daemon_home/.config/mise/conf.d"
else
  install -d -m 700 -o "$daemon_user" -g "$daemon_group" "$mise_config_dir"
fi
config_tmp="$(mktemp)"
service_tmp="$(mktemp)"
trap 'if [ -n "${var_tmp_probe:-}" ]; then rm -rf "$var_tmp_probe"; fi; rm -f "$config_tmp" "$service_tmp"' EXIT

cat >"$config_tmp" <<EOF
[tool_alias]
txing-unit-daemon = "github:mparkachov/txing"

[tools.txing-unit-daemon]
version = "latest"
asset_pattern = "$asset_pattern"
prerelease = $([ "$channel" = "feature" ] && printf true || printf false)
EOF

if [ "$channel" = "feature" ]; then
  cat >>"$config_tmp" <<'EOF'

[settings.github]
slsa = false
github_attestations = false
EOF
fi

if [ "$channel" = "stable" ]; then
  install -m 600 -o "$daemon_user" -g "$daemon_group" "$config_tmp" "$stable_config_file"
  rm -f "$mise_config_file"
  rmdir "$mise_config_dir" 2>/dev/null || true
  rm -rf "$tmp_root"
  command -v runuser >/dev/null 2>&1 || fail "runuser is required for stable install as '$daemon_user'"
  runuser -u "$daemon_user" -- env \
    "HOME=$daemon_home" \
    "$mise_bin" install
else
  install -m 600 -o "$daemon_user" -g "$daemon_group" "$config_tmp" "$mise_config_file"
  install -d -m 700 -o "$daemon_user" -g "$daemon_group" \
    "$tmp_root/mise" \
    "$tmp_root/mise-cache" \
    "$tmp_root/mise-tmp"
fi

{
  cat <<EOF
[Unit]
Description=Txing Unit Daemon
Wants=network-online.target systemd-time-wait-sync.service
After=network-online.target systemd-time-wait-sync.service time-sync.target

[Service]
Type=simple
# Runs as root because Phase 1 owns PWM/GPIO motor control directly.
WorkingDirectory=$daemon_home
KillSignal=SIGINT
TimeoutStartSec=180
TimeoutStopSec=30
Restart=on-failure
RestartSec=5

Environment=TXING_DAEMON_CONFIG_DIR=$daemon_config_dir
Environment=HOME=$daemon_home
EOF
  if [ "$channel" = "feature" ]; then
    cat <<EOF
Environment=MISE_CONFIG_DIR=$mise_config_dir
Environment=MISE_DATA_DIR=$tmp_root/mise
Environment=MISE_CACHE_DIR=$tmp_root/mise-cache
Environment=MISE_TMP_DIR=$tmp_root/mise-tmp
Environment=MISE_SHARED_INSTALL_DIRS=$daemon_home/.local/share/mise/installs
EOF
    printf 'Environment=MISE_PRERELEASES=1\n'
    cat <<EOF

ExecStartPre=/usr/bin/install -d -m 700 $tmp_root/mise $tmp_root/mise-cache $tmp_root/mise-tmp
ExecStartPre=-$mise_bin install
ExecStartPre=-/usr/bin/find $tmp_root/mise-cache $tmp_root/mise-tmp -mindepth 1 -maxdepth 1 -exec rm -rf {} +
EOF
  fi
  cat <<EOF
ExecStart=/usr/bin/env MISE_OFFLINE=1 $mise_bin exec -- txing-unit-daemon

[Install]
WantedBy=multi-user.target
EOF
} >"$service_tmp"

install -m 644 "$service_tmp" "$service_file"

if systemctl cat "$legacy_service_name" >/dev/null 2>&1 || [ -e "$legacy_service_file" ]; then
  systemctl disable --now "$legacy_service_name" >/dev/null 2>&1 || true
  rm -f "$legacy_service_file"
fi

systemctl daemon-reload
systemctl enable "$service_name"
systemctl restart "$service_name"

printf 'installed %s for %s channel\n' "$service_name" "$channel"
if [ "$channel" = "stable" ]; then
  printf '  mise config: %s\n' "$stable_config_file"
else
  printf '  mise config: %s\n' "$mise_config_file"
fi
printf '  systemd unit: %s\n' "$service_file"
printf '  mise binary: %s\n' "$mise_bin"
if [ "$channel" = "stable" ]; then
  printf '  stable install root: %s\n' "$stable_install_root"
else
  printf '  feature install root: %s\n' "$tmp_root/mise"
  printf '  stable fallback root: %s\n' "$stable_install_root"
fi
