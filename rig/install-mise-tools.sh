#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "error: $*" >&2
  exit 1
}

rig_home="${TXING_RIG_HOME:-${HOME:-}}"
owner="${TXING_GITHUB_OWNER:-mparkachov}"
repo="${TXING_GITHUB_REPO:-txing}"

[ -n "$rig_home" ] || fail "HOME is required"
[ -d "$rig_home" ] || fail "expected rig home directory $rig_home"

config_dir="$rig_home/.config/mise/conf.d"
config_file="$config_dir/txing-rig.toml"
install -d -m 700 "$config_dir"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat >"$tmp" <<EOF
[settings]
fetch_remote_versions_cache = "0s"

[tool_alias]
txing-sparkplug-manager = "github:$owner/$repo"
txing-ble-connectivity = "github:$owner/$repo"

[tools.txing-sparkplug-manager]
version = "latest"
asset_pattern = "txing-sparkplug-manager-linux-aarch64.tar.gz"

[tools.txing-ble-connectivity]
version = "latest"
asset_pattern = "txing-ble-connectivity-linux-aarch64.tar.gz"
EOF

install -m 600 "$tmp" "$config_file"
printf 'installed rig mise config: %s\n' "$config_file"
