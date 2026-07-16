#!/bin/sh
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "usage: assert-cyberbrick-musl.sh <binary> [kvs-master]" >&2
  exit 2
fi

binary="$1"
kind="${2:-daemon}"

if [ ! -x "$binary" ]; then
  echo "Cyberbrick release binary is missing or not executable: $binary" >&2
  exit 1
fi

file_output="$(file "$binary")"
printf '%s\n' "$file_output"
if ! printf '%s\n' "$file_output" | grep -E -q 'ELF 64-bit LSB.*ARM aarch64'; then
  echo "Cyberbrick release binary is not an ARM aarch64 ELF: $binary" >&2
  exit 1
fi

if ! readelf -l "$binary" | grep -Fq \
  '[Requesting program interpreter: /lib/ld-musl-aarch64.so.1]'; then
  echo "Cyberbrick release binary does not request /lib/ld-musl-aarch64.so.1: $binary" >&2
  exit 1
fi

ldd_output="$(ldd "$binary")"
printf '%s\n' "$ldd_output"
if printf '%s\n' "$ldd_output" | grep -Fq 'not found'; then
  echo "Cyberbrick release binary has unresolved shared libraries: $binary" >&2
  exit 1
fi
if ! printf '%s\n' "$ldd_output" | grep -Fq 'libc.musl-aarch64.so.1'; then
  echo "Cyberbrick release binary does not resolve musl libc: $binary" >&2
  exit 1
fi

case "$kind" in
  daemon|hardware-worker)
    ;;
  kvs-master)
    printf '%s\n' "$ldd_output" | grep -F 'libcamera.so.0.6'
    printf '%s\n' "$ldd_output" | grep -F 'libcamera-base.so.0.6'
    ;;
  *)
    echo "unknown Cyberbrick binary kind: $kind" >&2
    exit 2
    ;;
esac
