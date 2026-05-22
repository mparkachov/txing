# Common Board Dependencies

This directory contains shared board-side native dependencies.

Submodule content:

- `../../../modules/awslabs/amazon-kinesis-video-streams-webrtc-sdk-c/`: AWS KVS
  WebRTC C SDK, pinned by git submodule.

Generated content:

- `aws-kvs-webrtc-sdk-build/`
- `aws-kvs-webrtc-sdk-install/`
- `aws-kvs-webrtc-sdk-system-deps/`

Use `just unit::daemon::kvs-submodules` to initialize the SDK checkout and
`just unit::daemon::kvs-build-aws-sdk` on the Linux board host to rebuild the
generated native install. The build disables the SDK's third-party source
builds; distro packages provide OpenSSL, libcurl, libwebsockets, libsrtp2,
usrsctp, zlib, and log4cplus. The system-deps directory is a generated staging
prefix for system-library symlinks and AWS support libraries built by the SDK.
