#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: bash install-systemd.sh stable|feature

Installs or updates the root-owned txing unit daemon systemd service for the
selected mise channel. Run from a root shell during a writable-root maintenance
window.
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

ensure_writable_dir() {
  local label="$1"
  local dir="$2"
  local probe

  if [ ! -d "$dir" ]; then
    install -d -m 700 "$dir" || fail "cannot create $label directory: $dir"
  fi
  probe="$dir/.txing-write-test.$$"
  if ! : >"$probe" 2>/dev/null; then
    fail "$label directory is not writable: $dir"
  fi
  rm -f "$probe"
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
  fail "run this installer from a root shell"
fi
if [ "$(uname -s)" != "Linux" ]; then
  fail "this installer must run on Linux"
fi
command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
[ -d /run/systemd/system ] || fail "systemd does not appear to be PID 1"

root_home="${TXING_DAEMON_ROOT_HOME:-${HOME:-/root}}"
[ -n "$root_home" ] && [ "$root_home" != "/" ] || fail "root HOME must be set"
[ -d "$root_home" ] || fail "expected root home directory $root_home"

daemon_config_dir="${TXING_DAEMON_CONFIG_DIR:-$root_home/.config/txing/unit-daemon}"
if [ ! -r "$daemon_config_dir/daemon.env" ]; then
  printf 'warning: daemon runtime config is not readable yet: %s\n' "$daemon_config_dir/daemon.env" >&2
fi
if [ ! -r "$daemon_config_dir/private.pem.key" ]; then
  printf 'warning: daemon private key is not readable yet: %s\n' "$daemon_config_dir/private.pem.key" >&2
fi

root_options="$(findmnt -no OPTIONS / 2>/dev/null || true)"
case ",$root_options," in
  *,ro,*) fail "root filesystem is read-only; run root-rw before installing the service" ;;
esac

resolve_mise() {
  if [ -x "$root_home/.local/bin/mise" ]; then
    printf '%s\n' "$root_home/.local/bin/mise"
    return 0
  fi
  root_mise="$(command -v mise 2>/dev/null || true)"
  if [ -n "$root_mise" ] && [ -x "$root_mise" ]; then
    printf '%s\n' "$root_mise"
    return 0
  fi
  return 1
}

mise_bin="$(resolve_mise)" || fail "mise is required in the root shell; run: curl https://mise.run | sh"

mise_config_root="$root_home/.config/mise"
mise_config_dir="$mise_config_root/txing-unit-daemon"
mise_config_file="$mise_config_dir/config.toml"
stable_config_file="$mise_config_root/conf.d/txing-unit-daemon.toml"
service_name="txing-unit-daemon.service"
systemd_dir="/etc/systemd/system"
service_file="$systemd_dir/$service_name"
legacy_service_name="txing-unit-daemon-feature.service"
legacy_service_file="$systemd_dir/$legacy_service_name"
tmp_root="/var/tmp/txing/unit-daemon"
daemon_asset_pattern="txing-unit-daemon-linux-aarch64.tar.gz"
kvs_master_asset_pattern="txing-board-kvs-master-linux-aarch64.tar.gz"
stable_install_root="$root_home/.local/share/mise/installs/txing-unit-daemon"
kvs_master_stable_install_root="$root_home/.local/share/mise/installs/txing-board-kvs-master"
feature_trusted_config_paths="$mise_config_root:$mise_config_dir"
daemon_binary=""
kvs_master_binary=""
var_tmp_probe=""

run_root_mise() {
  env "HOME=$root_home" \
    "MISE_TRUSTED_CONFIG_PATHS=$mise_config_root" \
    "$mise_bin" "$@"
}

run_feature_mise() {
  env "HOME=$root_home" \
    "MISE_CONFIG_DIR=$mise_config_dir" \
    "MISE_DATA_DIR=$tmp_root/mise" \
    "MISE_CACHE_DIR=$tmp_root/mise-cache" \
    "MISE_TMP_DIR=$tmp_root/mise-tmp" \
    "MISE_SHARED_INSTALL_DIRS=$root_home/.local/share/mise/installs" \
    "MISE_TRUSTED_CONFIG_PATHS=$feature_trusted_config_paths" \
    "MISE_PRERELEASES=1" \
    "$mise_bin" "$@"
}

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
  stable_kvs_master_found=false
  for stable_kvs_master in "$kvs_master_stable_install_root"/*/txing-board-kvs-master; do
    if [ -x "$stable_kvs_master" ]; then
      stable_kvs_master_found=true
      break
    fi
  done
  [ "$stable_kvs_master_found" = true ] || fail "missing persistent stable KVS master install under $kvs_master_stable_install_root; install stable channel first"
  [ -d /var/tmp ] || fail "/var/tmp does not exist"
  [ -w /var/tmp ] || fail "/var/tmp is not writable"
  var_tmp_probe="$(mktemp -d /var/tmp/txing-unit-daemon-install.XXXXXX)"
  printf '#!/usr/bin/env sh\nexit 0\n' >"$var_tmp_probe/exec-test"
  chmod 700 "$var_tmp_probe/exec-test"
  "$var_tmp_probe/exec-test" >/dev/null 2>&1 || fail "/var/tmp must be mounted executable, without noexec"
fi

ensure_writable_dir "mise config" "$mise_config_root"
if [ "$channel" = "stable" ]; then
  ensure_writable_dir "stable mise config" "$mise_config_root/conf.d"
else
  ensure_writable_dir "feature mise config" "$mise_config_dir"
fi
ensure_writable_dir "daemon config" "$daemon_config_dir"
[ -d "$systemd_dir" ] || fail "missing systemd unit directory: $systemd_dir"
ensure_writable_dir "systemd unit" "$systemd_dir"

config_tmp="$(mktemp)"
service_tmp="$(mktemp)"
trap 'if [ -n "${var_tmp_probe:-}" ]; then rm -rf "$var_tmp_probe"; fi; rm -f "$config_tmp" "$service_tmp"' EXIT

cat >"$config_tmp" <<EOF
[settings]
fetch_remote_versions_cache = "10m"

[tool_alias]
txing-unit-daemon = "github:mparkachov/txing"
txing-board-kvs-master = "github:mparkachov/txing"

[tools.txing-unit-daemon]
version = "latest"
asset_pattern = "$daemon_asset_pattern"
prerelease = $([ "$channel" = "feature" ] && printf true || printf false)

[tools.txing-board-kvs-master]
version = "latest"
asset_pattern = "$kvs_master_asset_pattern"
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
  install -m 600 "$config_tmp" "$stable_config_file"
  rm -f "$mise_config_file"
  rmdir "$mise_config_dir" 2>/dev/null || true
  rm -rf "$tmp_root"
  run_root_mise cache clear >/dev/null 2>&1 || true
  run_root_mise install
  daemon_binary="$(run_root_mise which txing-unit-daemon)"
  kvs_master_binary="$(run_root_mise which txing-board-kvs-master)"
else
  install -m 600 "$config_tmp" "$mise_config_file"
  install -d -m 700 "$tmp_root/mise" "$tmp_root/mise-cache" "$tmp_root/mise-tmp"
  run_feature_mise cache clear >/dev/null 2>&1 || true
  run_feature_mise install
  daemon_binary="$(run_feature_mise which txing-unit-daemon)"
  kvs_master_binary="$(run_feature_mise which txing-board-kvs-master)"
fi
[ -x "$daemon_binary" ] || fail "resolved daemon binary is not executable: $daemon_binary"
[ -x "$kvs_master_binary" ] || fail "resolved KVS master binary is not executable: $kvs_master_binary"

{
  cat <<EOF
[Unit]
Description=Txing Unit Daemon
Wants=network-online.target systemd-time-wait-sync.service
After=network-online.target systemd-time-wait-sync.service time-sync.target
StartLimitIntervalSec=10min
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=$root_home
KillSignal=SIGINT
TimeoutStartSec=180
TimeoutStopSec=30
Restart=on-failure
RestartSec=5

Environment=TXING_DAEMON_CONFIG_DIR=$daemon_config_dir
Environment=HOME=$root_home
Environment=TXING_KVS_MASTER_COMMAND=$kvs_master_binary
EOF
  cat <<EOF
ExecStartPre=/usr/bin/test -x $daemon_binary
ExecStartPre=/usr/bin/test -x $kvs_master_binary
ExecStartPre=/usr/bin/echo txing-unit-daemon binary: $daemon_binary
ExecStartPre=-$daemon_binary --version
ExecStartPre=/usr/bin/echo txing-board-kvs-master binary: $kvs_master_binary
ExecStart=$daemon_binary

[Install]
WantedBy=multi-user.target
EOF
} >"$service_tmp"

install -m 644 "$service_tmp" "$service_file"

if systemctl cat "$legacy_service_name" >/dev/null 2>&1 || [ -e "$legacy_service_file" ]; then
  systemctl disable --now "$legacy_service_name" >/dev/null 2>&1 || true
  rm -f "$legacy_service_file"
fi

if systemctl list-unit-files NetworkManager-wait-online.service --no-legend --no-pager 2>/dev/null \
  | grep -q '^NetworkManager-wait-online\.service[[:space:]]'; then
  systemctl enable NetworkManager-wait-online.service >/dev/null
fi

systemctl daemon-reload
systemctl enable "$service_name"
systemctl reset-failed "$service_name" >/dev/null 2>&1 || true
systemctl restart "$service_name"

printf 'installed %s for %s channel\n' "$service_name" "$channel"
if [ "$channel" = "stable" ]; then
  printf '  mise config: %s\n' "$stable_config_file"
else
  printf '  mise config: %s\n' "$mise_config_file"
fi
printf '  systemd unit: %s\n' "$service_file"
printf '  mise binary: %s\n' "$mise_bin"
printf '  daemon binary: %s\n' "$daemon_binary"
printf '  KVS master binary: %s\n' "$kvs_master_binary"
printf '  daemon version: '
if ! "$daemon_binary" --version; then
  printf 'unavailable; resolved binary does not support --version\n'
fi
if [ "$channel" = "stable" ]; then
  printf '  stable install root: %s\n' "$stable_install_root"
  printf '  KVS master stable install root: %s\n' "$kvs_master_stable_install_root"
else
  printf '  feature install root: %s\n' "$tmp_root/mise"
  printf '  stable fallback root: %s\n' "$stable_install_root"
  printf '  KVS master stable fallback root: %s\n' "$kvs_master_stable_install_root"
fi
