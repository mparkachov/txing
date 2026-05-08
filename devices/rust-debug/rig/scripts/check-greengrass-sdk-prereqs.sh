#!/usr/bin/env bash
set -euo pipefail

if [ "$(uname -s)" != "Linux" ]; then
  echo "The aws-greengrass-component-sdk 1.0.3 build is Linux-only in this project." >&2
  exit 1
fi

missing=0

if ! command -v cc >/dev/null 2>&1; then
  echo "Missing C compiler: install build-essential." >&2
  missing=1
fi

if ! command -v clang >/dev/null 2>&1; then
  echo "Missing clang: install clang and libclang-dev." >&2
  missing=1
elif ! printf '#include <stdbool.h>\nint main(void){bool ok=true;return ok?0:1;}\n' | clang -x c -fsyntax-only - >/dev/null 2>&1; then
  echo "clang cannot find C standard headers such as stdbool.h." >&2
  echo "Install the host C development headers, for example on Ubuntu:" >&2
  echo "  sudo apt install build-essential clang libclang-dev libc6-dev" >&2
  missing=1
fi

if [ "$missing" -ne 0 ]; then
  exit 1
fi
