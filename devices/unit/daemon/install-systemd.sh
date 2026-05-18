#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: bash install-systemd.sh stable|feature

Generates the txing unit daemon mise config and systemd unit file for the
selected mise channel. Run this as the txing user during a writable-root
maintenance window.

Installing or updating the systemd service is a manual privileged host step.
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

if [ "$(id -u)" -eq 0 ]; then
  fail "run this generator as the daemon user, not as root"
fi
if [ "$(uname -s)" != "Linux" ]; then
  fail "this generator must run on Linux"
fi

daemon_user="${TXING_DAEMON_USER:-txing}"
current_user="$(id -un 2>/dev/null || true)"
[ "$current_user" = "$daemon_user" ] || fail "run this generator as '$daemon_user' user; current user is '${current_user:-unknown}'"
daemon_home="${HOME:-}"
[ -n "$daemon_home" ] && [ "$daemon_home" != "/" ] || fail "HOME must point at the daemon user's home directory"
[ -d "$daemon_home" ] || fail "expected daemon home directory $daemon_home"

daemon_config_dir="${TXING_DAEMON_CONFIG_DIR:-$daemon_home/.config/txing/unit-daemon}"
if [ ! -r "$daemon_config_dir/.env" ]; then
  printf 'warning: daemon runtime config is not readable yet: %s\n' "$daemon_config_dir/.env" >&2
fi
if [ ! -r "$daemon_config_dir/private.pem.key" ]; then
  printf 'warning: daemon private key is not readable yet: %s\n' "$daemon_config_dir/private.pem.key" >&2
fi

root_options="$(findmnt -no OPTIONS / 2>/dev/null || true)"
case ",$root_options," in
  *,ro,*) fail "root filesystem is read-only; enter a writable-root maintenance window before generating config" ;;
esac

resolve_mise() {
  if [ -x "$daemon_home/.local/bin/mise" ]; then
    printf '%s\n' "$daemon_home/.local/bin/mise"
    return 0
  fi
  user_mise="$(command -v mise 2>/dev/null || true)"
  if [ -n "$user_mise" ] && [ -x "$user_mise" ]; then
    printf '%s\n' "$user_mise"
    return 0
  fi
  return 1
}

mise_bin="$(resolve_mise)" || fail "mise is required; install it for the '$daemon_user' user first"

mise_config_dir="$daemon_home/.config/mise/txing-unit-daemon"
mise_config_file="$mise_config_dir/config.toml"
stable_config_file="$daemon_home/.config/mise/conf.d/txing-unit-daemon.toml"
service_name="txing-unit-daemon.service"
generated_systemd_dir="$daemon_config_dir/systemd"
generated_service_file="$generated_systemd_dir/$service_name"
manual_service_file="/etc/systemd/system/$service_name"
tmp_root="/var/tmp/txing/unit-daemon"
daemon_asset_pattern="txing-unit-daemon-linux-aarch64.tar.gz"
kvs_master_asset_pattern="txing-board-kvs-master-linux-aarch64.tar.gz"
stable_install_root="$daemon_home/.local/share/mise/installs/txing-unit-daemon"
kvs_master_stable_install_root="$daemon_home/.local/share/mise/installs/txing-board-kvs-master"
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

install -d -m 700 "$daemon_home/.config/mise"
if [ "$channel" = "stable" ]; then
  install -d -m 700 "$daemon_home/.config/mise/conf.d"
else
  install -d -m 700 "$mise_config_dir"
fi
install -d -m 700 "$generated_systemd_dir"
config_tmp="$(mktemp)"
service_tmp="$(mktemp)"
trap 'if [ -n "${var_tmp_probe:-}" ]; then rm -rf "$var_tmp_probe"; fi; rm -f "$config_tmp" "$service_tmp"' EXIT

cat >"$config_tmp" <<EOF
[settings]
fetch_remote_versions_cache = "0s"

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
  "$mise_bin" cache clear >/dev/null 2>&1 || true
  env \
    "HOME=$daemon_home" \
    "$mise_bin" install
else
  install -m 600 "$config_tmp" "$mise_config_file"
fi

{
  cat <<EOF
# Generated by txing unit daemon systemd generator.
# Install manually as $manual_service_file during host maintenance.

[Unit]
Description=Txing Unit Daemon
Wants=network-online.target systemd-time-wait-sync.service
After=network-online.target systemd-time-wait-sync.service time-sync.target

[Service]
Type=simple
# Runs as root because the daemon owns PWM/GPIO motor control directly.
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
ExecStartPre=-$mise_bin upgrade txing-unit-daemon
ExecStartPre=-$mise_bin upgrade txing-board-kvs-master
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

install -m 644 "$service_tmp" "$generated_service_file"

printf 'generated %s for %s channel\n' "$service_name" "$channel"
if [ "$channel" = "stable" ]; then
  printf '  mise config: %s\n' "$stable_config_file"
else
  printf '  mise config: %s\n' "$mise_config_file"
fi
printf '  generated systemd unit: %s\n' "$generated_service_file"
printf '  manual systemd target: %s\n' "$manual_service_file"
printf '  mise binary: %s\n' "$mise_bin"
if [ "$channel" = "stable" ]; then
  printf '  stable install root: %s\n' "$stable_install_root"
  printf '  KVS master stable install root: %s\n' "$kvs_master_stable_install_root"
else
  printf '  feature install root: %s\n' "$tmp_root/mise"
  printf '  stable fallback root: %s\n' "$stable_install_root"
  printf '  KVS master stable fallback root: %s\n' "$kvs_master_stable_install_root"
fi
