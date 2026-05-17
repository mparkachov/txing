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
[tool_alias]
txing-sparkplug-manager = "github:$owner/$repo"
txing-ble-connectivity = "github:$owner/$repo"
txing-aws-connectivity = "github:$owner/$repo"
txing-rig-deploy = "github:$owner/$repo"
txing-greengrass-lite = "github:aws-greengrass/aws-greengrass-lite"

[tools.txing-sparkplug-manager]
version = "latest"
asset_pattern = "txing-sparkplug-manager-linux-aarch64.tar.gz"

[tools.txing-ble-connectivity]
version = "latest"
asset_pattern = "txing-ble-connectivity-linux-aarch64.tar.gz"

[tools.txing-aws-connectivity]
version = "latest"
asset_pattern = "txing-aws-connectivity-linux-aarch64.tar.gz"

[tools.txing-rig-deploy]
version = "latest"
asset_pattern = "txing-rig-deploy-linux-aarch64.tar.gz"

[tools.txing-greengrass-lite]
version = "latest"
asset_pattern = "aws-greengrass-lite-deb-arm64.zip"
EOF

install -m 600 "$tmp" "$config_file"
printf 'installed rig mise config: %s\n' "$config_file"
