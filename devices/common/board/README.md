# Common Board Dependencies

This directory contains shared board-side native dependencies.

Tracked content:

- `aws-kvs-webrtc-sdk/`: AWS KVS WebRTC C SDK, pinned by git submodule.

Generated content:

- `aws-kvs-webrtc-sdk-build/`
- `aws-kvs-webrtc-sdk-install/`

Use `just unit::board::submodules` to initialize the SDK checkout and
`just unit::board::build-aws-sdk` to rebuild the generated native install.
