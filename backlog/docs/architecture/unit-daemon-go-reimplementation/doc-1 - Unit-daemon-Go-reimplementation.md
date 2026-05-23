---
id: doc-1
title: Unit daemon Go reimplementation
type: specification
created_date: '2026-05-23 14:29'
updated_date: '2026-05-23 14:29'
---
# Unit Daemon Go Reimplementation

## Goal
Replace the current Rust `txing-unit-daemon` with a Go implementation while preserving the daemon's public contract, runtime behavior, installation name, and release asset name. In the same milestone, remove the Rust daemon from the active unit build surface after parity validation passes.

## Affected Components
- Unit board daemon under `devices/unit/daemon`.
- Board video bridge and hardware worker protobuf consumers under `devices/unit/proto`.
- Native KVS worker under `devices/unit/board/kvs_master`.
- Release, versioning, artifact, install, and board runtime documentation.

## Stable Contracts
- Daemon binary remains `txing-unit-daemon`.
- Release asset remains `txing-unit-daemon-linux-aarch64.tar.gz`.
- Config directory remains `/root/.config/txing/unit-daemon` and env file remains `daemon.env`.
- CLI flags, `TXING_*` env variables, MQTT topics, Thing Shadow names/schemas, MCP protocol version, MCP tool behavior, JSON-RPC error behavior, and socket paths remain behaviorally equivalent.
- Existing proto package names, service names, field numbers, and wire semantics remain unchanged.

## Intentional Renames
- `txing-board-kvs-master` becomes `txing-unit-kvs-master` everywhere active: executable, release asset, service, docs/tests, CMake target, mise alias, and worker/client identity.
- `txing-board.target` becomes `txing-unit.target` as the common board runtime systemd target.
- The KVS channel name remains `<thing-id>-board-video`; `TXING_BOARD_VIDEO_*` names and retained video topics remain unchanged.

## Implementation Direction
- Use Go 1.24+ with AWS SDK for Go v2, Eclipse Paho MQTT Go, Go gRPC/protobuf, and standard-library TLS/HTTP.
- Keep the daemon as a replacement, not a parallel runtime: no feature flag, alternate service, or protocol version.
- Port the Rust test coverage one-for-one before removing Rust from active build and release surfaces.

## Risks
- Runtime parity is high-risk because the daemon owns board, MCP, video, and shadow publication contracts.
- Release/install rename is operationally sensitive because deployed boards must remove or replace old systemd units manually.
- AWS and board hardware actions are not part of implementation; validation is repo-local unless a future task explicitly adds manual field validation.
