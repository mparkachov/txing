# Board Video Bridge Contract

`txing-unit-daemon` and `txing-unit-kvs-master` communicate over a local,
versioned gRPC contract. The proto source is:

```text
devices/unit/proto/txing/unit/board_video/v1/board_video.proto
```

The daemon is the gRPC server. The native KVS master is the client. Both
processes are independent systemd services; systemd owns service start order,
restart behavior, and installation. The bridge uses a manually configured Unix
domain socket, normally:

```text
/run/txing-unit-daemon/board-video-bridge.sock
```

## Surface

The v1 service is `txing.unit.board_video.v1.BoardVideoBridge`.

- `GetWorkerConfig(WorkerHello) -> WorkerConfig`
- `RefreshCredentials(RefreshCredentialsRequest) -> KvsCredentials`
- `ReportVideoState(VideoState) -> Ack`
- `OpenMcpSession(OpenMcpSessionRequest) -> Ack`
- `HandleMcp(McpRequest) -> McpResponse`
- `CloseMcpSession(CloseMcpSessionRequest) -> Ack`

`GetWorkerConfig` is the worker bootstrap boundary. It returns AWS region,
KVS signaling channel name, worker client id, WebRTC MCP data-channel label,
MCP response timeout, KVS network preferences, and temporary credentials.

`RefreshCredentials` returns a fresh temporary credential set before the
current set expires. The daemon remains the credential authority.

`ReportVideoState` is coarse state only: `STARTING`, `READY`, or `ERROR`, plus
viewer count and optional error text. `READY` means the worker is ready enough
for the daemon to advertise WebRTC MCP transport; it is not a media-quality
guarantee.

`OpenMcpSession`, `HandleMcp`, and `CloseMcpSession` forward MCP session
lifecycle and opaque MCP JSON-RPC bytes. `txing-unit-kvs-master` does not
parse MCP tools and does not enforce active-control policy.

## Ownership

Daemon-owned:

- board, video, MCP, and capability publication
- KVS worker config and temporary credentials
- active-control ownership, takeover, epoch checks, watchdogs, and REDCON
- MCP JSON-RPC parsing and tool policy

Worker-owned:

- camera capture and H.264 encode
- AWS KVS WebRTC master session
- WebRTC peer connections and data-channel transport
- bridge retry while the daemon socket is unavailable

## MCP Sessions

Every MCP transport path uses a distinct `mcp_session_id`. Opening a bridge
session makes the daemon aware of the session, but it does not grant active
control. Control takeover remains an MCP semantic through
`control.activate({ "takeover": true })`.

Future cloud/control-only paths should reuse the same daemon MCP model with
distinct session ids and transport metadata. This contract intentionally does
not add admission, scheduling, or takeover policy to the worker.

## Deployment Boundaries

This contract does not change the board read-only-root layout. Installation
remains manual: install both binaries, create/update root-owned config, create
or update systemd units, reload systemd, and restart services while root is
writable.

The contract is language-neutral. Either component may be replaced by another
implementation as long as it preserves the v1 proto semantics and field
numbers.
