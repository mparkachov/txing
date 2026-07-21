#!/bin/sh
# Builds the static protobuf/gRPC stack for board hardware workers into the
# given prefix. Alpine apk ships no static archives for this stack (doc-30),
# so it is source-built with tags pinned to the apk package versions; the
# prefix is reused while the marker below matches, so cached prefixes survive
# across builds. Requires an aarch64 Alpine environment with build-base,
# cmake, git, curl, linux-headers, openssl-libs-static, and zlib-static.
set -eu

prefix="${1:?usage: build-board-static-toolchain.sh <prefix>}"

absl_version="20250814.1"
protobuf_version="31.1"
re2_version="2025-11-05"
cares_version="1.34.8"
grpc_version="1.76.0"

marker="$prefix/.txing-static-toolchain"
spec="alpine=$(cat /etc/alpine-release) absl=$absl_version protobuf=$protobuf_version re2=$re2_version cares=$cares_version grpc=$grpc_version"
if [ -f "$marker" ] && [ "$(cat "$marker")" = "$spec" ]; then
  printf 'reusing cached static toolchain (%s)\n' "$spec"
  exit 0
fi

printf 'building static toolchain (%s)\n' "$spec"
install -d "$prefix"
find "$prefix" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
src="$(mktemp -d "${TMPDIR:-/tmp}/txing-static-toolchain.XXXXXX")"
cleanup() {
  rm -rf "$src"
}
trap cleanup EXIT
jobs="$(nproc)"
static_flags="-DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_INSTALL_PREFIX=$prefix -DCMAKE_PREFIX_PATH=$prefix -DCMAKE_CXX_STANDARD=17"

curl -fsSL "https://github.com/abseil/abseil-cpp/archive/refs/tags/$absl_version.tar.gz" | tar -xz -C "$src"
cmake -S "$src/abseil-cpp-$absl_version" -B "$src/build-absl" $static_flags \
  -DABSL_PROPAGATE_CXX_STD=ON -DABSL_BUILD_TESTING=OFF -DABSL_ENABLE_INSTALL=ON
cmake --build "$src/build-absl" -j "$jobs"
cmake --install "$src/build-absl" >/dev/null

curl -fsSL "https://github.com/protocolbuffers/protobuf/archive/refs/tags/v$protobuf_version.tar.gz" | tar -xz -C "$src"
cmake -S "$src/protobuf-$protobuf_version" -B "$src/build-protobuf" $static_flags \
  -Dprotobuf_BUILD_TESTS=OFF -Dprotobuf_BUILD_SHARED_LIBS=OFF -Dprotobuf_ABSL_PROVIDER=package
cmake --build "$src/build-protobuf" -j "$jobs"
cmake --install "$src/build-protobuf" >/dev/null

curl -fsSL "https://github.com/google/re2/archive/refs/tags/$re2_version.tar.gz" | tar -xz -C "$src"
cmake -S "$src/re2-$re2_version" -B "$src/build-re2" $static_flags \
  -DRE2_BUILD_TESTING=OFF
cmake --build "$src/build-re2" -j "$jobs"
cmake --install "$src/build-re2" >/dev/null

curl -fsSL "https://github.com/c-ares/c-ares/archive/refs/tags/v$cares_version.tar.gz" | tar -xz -C "$src"
cmake -S "$src/c-ares-$cares_version" -B "$src/build-cares" $static_flags \
  -DCARES_STATIC=ON -DCARES_SHARED=OFF -DCARES_BUILD_TOOLS=OFF
cmake --build "$src/build-cares" -j "$jobs"
cmake --install "$src/build-cares" >/dev/null

git clone --depth 1 --branch "v$grpc_version" https://github.com/grpc/grpc "$src/grpc"
(
  cd "$src/grpc"
  git submodule update --init --depth 1 \
    third_party/xds third_party/envoy-api third_party/googleapis \
    third_party/opencensus-proto third_party/protoc-gen-validate
)
cmake -S "$src/grpc" -B "$src/build-grpc" $static_flags \
  -DgRPC_INSTALL=ON -DgRPC_BUILD_TESTS=OFF \
  -DgRPC_ABSL_PROVIDER=package -DgRPC_PROTOBUF_PROVIDER=package \
  -DgRPC_RE2_PROVIDER=package -DgRPC_CARES_PROVIDER=package \
  -DgRPC_SSL_PROVIDER=package -DgRPC_ZLIB_PROVIDER=package \
  -DOPENSSL_USE_STATIC_LIBS=TRUE -DZLIB_USE_STATIC_LIBS=ON \
  -DgRPC_BUILD_GRPC_CSHARP_PLUGIN=OFF -DgRPC_BUILD_GRPC_NODE_PLUGIN=OFF \
  -DgRPC_BUILD_GRPC_OBJECTIVE_C_PLUGIN=OFF -DgRPC_BUILD_GRPC_PHP_PLUGIN=OFF \
  -DgRPC_BUILD_GRPC_PYTHON_PLUGIN=OFF -DgRPC_BUILD_GRPC_RUBY_PLUGIN=OFF
cmake --build "$src/build-grpc" -j "$jobs"
cmake --install "$src/build-grpc" >/dev/null

printf '%s' "$spec" >"$marker"
