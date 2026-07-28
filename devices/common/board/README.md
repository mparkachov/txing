# Board Native Workers

The single native board implementation shared by every board device type. The
authoritative board documentation lives in
[../../../docs/components/board.md](../../../docs/components/board.md).

- `daemon/` — Go daemon (`txing-<device>-daemon`)
- `kvs_master/` — camera and AWS KVS WebRTC signaling worker
  (`txing-<device>-kvs-master`)
- `hardware_worker/` — board-local motor hardware worker
  (`txing-<device>-hardware-worker`)

The device type is a build input rather than a source axis. Builds pass
`TXING_BOARD_DEVICE_TYPE`, which selects the proto package under
`devices/<device>/proto`, the binary names, the hardware socket path, and the
release stream in `release/versions/<device>` that the version is injected from.
Per-device material — the `manifest.toml` profile, shadow schemas, the web
adapter, and the proto package — stays under `devices/<device>/`.

Build and test through the shared recipes, which take the device type as their
first argument:

```sh
just common::board::hardware-test-native unit
just common::board::kvs-test-native cyberbrick
just common::board::docker-build unit
```

## Legacy generated content

This directory also holds legacy generated board-side native dependency
outputs, kept only so existing checkouts can clean them:

- `aws-kvs-webrtc-sdk-build/`
- `aws-kvs-webrtc-sdk-install/`
- `aws-kvs-webrtc-sdk-system-deps/`

Current KVS master builds fetch and build the pinned AWS KVS WebRTC C SDK under
`kvs_master/build/` through CMake `ExternalProject`; the SDK is no longer
checked out as a repository submodule. Use `just common::board::clean <device>`
to remove these legacy outputs. The active build disables the SDK's third-party
source builds; distro packages provide OpenSSL, libcurl, libwebsockets,
libsrtp2, usrsctp, zlib, log4cplus, protobuf, and gRPC.
