#!/usr/bin/env bash
set -euo pipefail

web_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$web_dir/.." && pwd)"

for device_web_dir in "$repo_root"/devices/*/web; do
  if [ ! -d "$device_web_dir" ]; then
    continue
  fi
  ln -snf ../../../web/node_modules "$device_web_dir/node_modules"
done
