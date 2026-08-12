cyberbrick_dir := source_directory()
project_root := canonicalize(cyberbrick_dir + "/../..")
tmp_dir := project_root + "/tmp"

test-bindings:
    #!/bin/sh
    set -eu
    output="{{tmp_dir}}/cyberbrick-mavlink-golden-frame-test"
    c++ -std=c++17 -Wno-address-of-packed-member \
      -I"{{cyberbrick_dir}}/mavlink/include" \
      "{{cyberbrick_dir}}/mavlink/tests/golden_frame_test.cpp" \
      -o "$output"
    "$output"
    cd "{{project_root}}/office"
    ./node_modules/.bin/tsc -p "../devices/cyberbrick/mavlink/typescript/tsconfig.json"
    bun test test/mavlink-frame.test.ts

regeneration-check:
    #!/bin/sh
    set -eu
    "{{cyberbrick_dir}}/mavlink/scripts/regeneration-check.sh"
