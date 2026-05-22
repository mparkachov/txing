#!/bin/sh
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
office_dir="$(CDPATH= cd -- "$script_dir/.." && pwd)"
repo_root="$(cd "$office_dir/.." && pwd)"

for device_web_dir in "$repo_root"/devices/*/web; do
  if [ ! -d "$device_web_dir" ]; then
    continue
  fi
  ln -snf ../../../office/node_modules "$device_web_dir/node_modules"
done
