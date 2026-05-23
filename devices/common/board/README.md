# Common Board Dependencies

This directory contains legacy generated board-side native dependency outputs.
Current KVS master builds fetch and build the pinned AWS KVS WebRTC C SDK under
`devices/unit/board/kvs_master/build/` through CMake `ExternalProject`; the SDK
is no longer checked out as a repository submodule.

Legacy generated content:

- `aws-kvs-webrtc-sdk-build/`
- `aws-kvs-webrtc-sdk-install/`
- `aws-kvs-webrtc-sdk-system-deps/`

Use `just unit::daemon::kvs-clean` to remove these legacy outputs. The active
build disables the SDK's third-party source builds; distro packages provide
OpenSSL, libcurl, libwebsockets, libsrtp2, usrsctp, zlib, log4cplus, protobuf,
and gRPC.
