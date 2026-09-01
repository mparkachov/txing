#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
mavlink_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
project_root=$(CDPATH= cd -- "$mavlink_dir/../../../.." && pwd)
work_dir=$(mktemp -d "$project_root/tmp/mavlink-regeneration.XXXXXX")

c_library_url=https://github.com/mavlink/c_library_v2.git
c_library_commit=a3661c0a85dc1de1826f5c95863048af3e2b0d04
pymavlink_url=https://github.com/ArduPilot/pymavlink.git
pymavlink_commit=774840a8e6450c33cd97a33b86e3af5d3d1ea173

fetch_tree() {
  repository_url=$1
  commit=$2
  destination=$3
  shift 3
  mkdir -p "$destination"
  git -C "$destination" init --quiet
  git -C "$destination" fetch --quiet --depth 1 "$repository_url" "$commit"
  actual_commit=$(git -C "$destination" rev-parse FETCH_HEAD)
  if [ "$actual_commit" != "$commit" ]; then
    echo "fetched $actual_commit, expected $commit" >&2
    exit 1
  fi
  if [ "$#" -gt 0 ]; then
    git -C "$destination" archive FETCH_HEAD "$@" | tar -x -C "$destination"
  else
    git -C "$destination" archive FETCH_HEAD | tar -x -C "$destination"
  fi
}

fetch_tree "$c_library_url" "$c_library_commit" "$work_dir/c-library" message_definitions
fetch_tree "$pymavlink_url" "$pymavlink_commit" "$work_dir/pymavlink" \
  generator/__init__.py \
  generator/mavcrc.py \
  generator/mavgen.py \
  generator/mavgen_c.py \
  generator/mavgen_typescript.py \
  generator/mavparse.py \
  generator/mavschema.xsd \
  generator/mavtemplate.py \
  generator/C/include_v2.0 \
  tools/mavgen.py

python3 -m venv "$work_dir/venv"
"$work_dir/venv/bin/pip" install --disable-pip-version-check --quiet fastcrc==0.3.6 lxml==6.1.1

generator="$work_dir/pymavlink/tools/mavgen.py"
definitions="$work_dir/c-library/message_definitions/common.xml"
PYTHONPATH="$work_dir" "$work_dir/venv/bin/python" "$generator" --lang C --wire-protocol 2.0 --output "$work_dir/generated-c" "$definitions"
mkdir -p "$work_dir/generated-typescript"
PYTHONPATH="$work_dir" "$work_dir/venv/bin/python" "$generator" --lang TypeScript --wire-protocol 2.0 --output "$work_dir/generated-typescript" "$definitions"

"$work_dir/venv/bin/python" - "$work_dir/generated-typescript" <<'PY'
from pathlib import Path
import re
import sys

generated = Path(sys.argv[1])
for path in generated.rglob("*.ts"):
    contents = re.sub(r"(?m)^(?:\t+ +| +|\t{2,}(?!\[))", "// ", path.read_text())
    if path.parent.name == "messages":
        contents = contents.replace(
            "'@ifrunistuttgart/node-mavlink'", "'../../runtime'"
        )
    path.write_text(contents)
registry = generated / "message-registry.ts"
registry.write_text(registry.read_text().replace(
    "'@ifrunistuttgart/node-mavlink'", "'../runtime'"
))
PY

vendor_c="$mavlink_dir/include/mavlink/v2.0"
vendor_ts="$mavlink_dir/typescript/generated"

for dialect in minimal standard common; do
  diff -ru -x version.h "$work_dir/generated-c/$dialect" "$vendor_c/$dialect"
done
for header in checksum.h mavlink_conversions.h mavlink_get_info.h mavlink_helpers.h mavlink_sha256.h mavlink_types.h protocol.h; do
  diff -u "$work_dir/generated-c/$header" "$vendor_c/$header"
done
for dialect in minimal standard common; do
  sed 's/^#define MAVLINK_BUILD_DATE .*/#define MAVLINK_BUILD_DATE "<normalized>"/' "$work_dir/generated-c/$dialect/version.h" > "$work_dir/generated-$dialect-version.h"
  sed 's/^#define MAVLINK_BUILD_DATE .*/#define MAVLINK_BUILD_DATE "<normalized>"/' "$vendor_c/$dialect/version.h" > "$work_dir/vendor-$dialect-version.h"
  diff -u "$work_dir/generated-$dialect-version.h" "$work_dir/vendor-$dialect-version.h"
done
diff -ru "$work_dir/generated-typescript/enums" "$vendor_ts/enums"
diff -ru "$work_dir/generated-typescript/messages" "$vendor_ts/messages"
diff -u "$work_dir/generated-typescript/message-registry.ts" "$vendor_ts/message-registry.ts"

echo "Board MAVLink bindings match pinned generator inputs."
