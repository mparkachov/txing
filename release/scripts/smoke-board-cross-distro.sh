#!/bin/sh
# Executes a board binary in every userland its linkage kind promises (doc-32):
# static binaries must run on both bare debian:trixie and bare pinned Alpine
# (kernel-only dependency), while the musl-dynamic KVS master runs on Alpine
# only, against the documented runtime package superset. The last output line
# of each run must equal the expected version line. Requires a native
# linux/arm64 container runtime. Local development uses nerdctl; the release
# workflows set TXING_CONTAINER_CLI=docker for GitHub-hosted runners.
set -eu

if [ "$#" -ne 3 ]; then
  echo "usage: smoke-board-cross-distro.sh <binary> <static|musl-libcamera> <expected-version-line>" >&2
  exit 2
fi

binary="$1"
kind="$2"
expected="$3"

debian_image="debian:trixie"
alpine_image="docker.io/library/alpine:3.24.1"
platform="linux/arm64"
alpine_runtime_packages="ca-certificates curl-dev openssl-dev log4cplus-dev libsrtp-dev libusrsctp-dev libwebsockets-dev zlib-dev libcamera-dev protobuf-dev grpc-dev"
container_cli="${TXING_CONTAINER_CLI:-nerdctl}"

if [ ! -x "$binary" ]; then
  echo "Board smoke binary is missing or not executable: $binary" >&2
  exit 1
fi
bin_dir="$(cd "$(dirname "$binary")" && pwd)"
bin_name="$(basename "$binary")"

case "$container_cli" in
  nerdctl)
    command -v nerdctl >/dev/null 2>&1 || {
      echo "nerdctl is required for the board cross-distro smoke." >&2
      exit 1
    }
    server_platform="$(nerdctl info --format '{{.OSType}}/{{.Architecture}}')"
    ;;
  docker)
    command -v docker >/dev/null 2>&1 || {
      echo "docker is required for the board cross-distro smoke in this environment." >&2
      exit 1
    }
    server_platform="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')"
    ;;
  *)
    echo "Unsupported TXING_CONTAINER_CLI: $container_cli (expected nerdctl or docker)." >&2
    exit 2
    ;;
esac

case "$server_platform" in
  linux/aarch64|linux/arm64) ;;
  *)
    echo "Board cross-distro smoke requires a native linux/arm64 container runtime, got: $server_platform" >&2
    exit 1
    ;;
esac

run_smoke() {
  smoke_image="$1"
  smoke_setup="$2"
  output="$("$container_cli" run --rm \
    --platform "$platform" \
    --mount "type=bind,source=$bin_dir,target=/smoke,readonly" \
    "$smoke_image" \
    sh -ec "$smoke_setup/smoke/$bin_name --version")"
  actual="$(printf '%s\n' "$output" | tail -n 1)"
  if [ "$actual" != "$expected" ]; then
    echo "Expected '$expected' from $bin_name on $smoke_image, got '$actual'." >&2
    exit 1
  fi
  printf 'smoke OK: %s on %s (%s)\n' "$bin_name" "$smoke_image" "$actual"
}

case "$kind" in
  static)
    run_smoke "$debian_image" ""
    run_smoke "$alpine_image" ""
    ;;
  musl-libcamera)
    run_smoke "$alpine_image" "apk add --no-cache -q $alpine_runtime_packages >/dev/null 2>&1; "
    ;;
  *)
    echo "unknown board binary linkage kind: $kind" >&2
    exit 2
    ;;
esac
