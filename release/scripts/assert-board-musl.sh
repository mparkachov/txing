#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: assert-board-musl.sh <binary> <static|musl-libcamera>" >&2
  exit 2
fi

binary="$1"
kind="$2"

if [ ! -x "$binary" ]; then
  echo "Board release binary is missing or not executable: $binary" >&2
  exit 1
fi

file_output="$(file "$binary")"
printf '%s\n' "$file_output"
if ! printf '%s\n' "$file_output" | grep -E -q 'ELF 64-bit LSB.*ARM aarch64'; then
  echo "Board release binary is not an ARM aarch64 ELF: $binary" >&2
  exit 1
fi

case "$kind" in
  static)
    # Alpine gcc defaults to PIE, so -static produces a static-PIE: file says
    # 'static-pie linked' and the hard invariant is the absent PT_INTERP header.
    if ! printf '%s\n' "$file_output" | grep -E -q 'statically linked|static-pie linked'; then
      echo "Board release binary is not statically linked: $binary" >&2
      exit 1
    fi
    if readelf -l "$binary" | grep -Fq 'INTERP'; then
      echo "Board release binary unexpectedly has an ELF interpreter: $binary" >&2
      exit 1
    fi
    ;;
  musl-libcamera)
    if ! readelf -l "$binary" | grep -Fq \
      '[Requesting program interpreter: /lib/ld-musl-aarch64.so.1]'; then
      echo "Board release binary does not request /lib/ld-musl-aarch64.so.1: $binary" >&2
      exit 1
    fi
    ldd_output="$(ldd "$binary")"
    printf '%s\n' "$ldd_output"
    if printf '%s\n' "$ldd_output" | grep -Fq 'not found'; then
      echo "Board release binary has unresolved shared libraries: $binary" >&2
      exit 1
    fi
    if ! printf '%s\n' "$ldd_output" | grep -Fq 'libc.musl-aarch64.so.1'; then
      echo "Board release binary does not resolve musl libc: $binary" >&2
      exit 1
    fi
    printf '%s\n' "$ldd_output" | grep -F 'libcamera.so.0.6'
    printf '%s\n' "$ldd_output" | grep -F 'libcamera-base.so.0.6'
    ;;
  *)
    echo "unknown board binary linkage kind: $kind" >&2
    exit 2
    ;;
esac
