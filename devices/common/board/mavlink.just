set shell := ["sh", "-eu", "-c"]
set quiet := true

board_dir := source_directory()
project_root := canonicalize(board_dir + "/../../..")
tmp_dir := project_root + "/tmp"

test-bindings:
    #!/bin/sh
    set -eu
    output="{{tmp_dir}}/board-mavlink-golden-frame-test"
    c++ -std=c++17 -Wno-address-of-packed-member \
      -I"{{board_dir}}/mavlink/include" \
      "{{board_dir}}/mavlink/tests/golden_frame_test.cpp" \
      -o "$output"
    "$output"
    cd "{{project_root}}/office"
    ./node_modules/.bin/tsc -p "../devices/common/board/mavlink/typescript/tsconfig.json"
    bun test test/mavlink-frame.test.ts

regeneration-check:
    #!/bin/sh
    set -eu
    "{{board_dir}}/mavlink/scripts/regeneration-check.sh"
