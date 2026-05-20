#!/usr/bin/env bash
set -euo pipefail

office_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$office_dir/.." && pwd)"

for device_web_dir in "$repo_root"/devices/*/web; do
  if [ ! -d "$device_web_dir" ]; then
    continue
  fi
  ln -snf ../../../office/node_modules "$device_web_dir/node_modules"
done
