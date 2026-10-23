# Native QGroundControl adapter acceptance — #166

The native C++ manual operator implements localhost UDP observation and explicit
free-lease control. The automated evidence below uses real loopback sockets and
the production Session/Actions boundary, including a complete real KVS SDK peer
path. It does not claim a QGroundControl GUI run, real flight-controller parameter
retrieval, motion or physical contention. Those secured/lifted-TBot checks belong
to #167. No live device is controlled by these tests.

## Runtime and client behavior

`just agent::run <thing-id> [udp-port] [--control]` builds when needed and execs
the foreground C++ binary. The agent listens on `127.0.0.1:14551`; QGC's UDP
link listens on 14550 and targets `127.0.0.1:14551`. An optional
`--qgc-port <port>` changes the destination and expected source port. Both must
be distinct integers from 1 to 65535. Binding fails before AWS initialization
if the local port is occupied, with the address and a remedy in the error.
Exact setup and operator commands are in the
[agent README](../agent/README.md#local-qgroundcontrol).

The operator immediately sends telemetry to that endpoint, before client
presence. A complete initial MAVLink 1 heartbeat, checked using the repository's
pinned generated heartbeat definition/CRC, establishes presence without going
to the board. MAVLink 2 uses structural validation only: no dialect allowlist,
CRC recalculation, signature rewriting or ID changes. Each datagram contains
complete frames; concatenated frames are split into one binary board message
per frame. A malformed/truncated datagram is rejected in full, including a valid
prefix; fragments from separate datagrams are never joined. Polling is bounded
to 32 datagrams, 16 KiB and 32 frames per datagram. Other source endpoints cannot
establish presence, extend authority or inject uplink.

Observation is default. `--control` makes one attempt after client presence and
telemetry readiness, through ordinary Actions with `takeover=false`. No packet
is buffered for a future grant; QGC's normal retries supply later traffic.
A busy owner is preserved. The same lease carries parameter/configuration and
arm/disarm/re-arm traffic. Failed, busy or lost attempts never automatically
reacquire; another attempt requires an explicit new `--control` run.

Valid client traffic refreshes presence; telemetry downlink does not. Five
seconds without client traffic releases control. UDP provides no close event,
so closing the QGC link/socket is detected by that same deadline. A local socket
failure or explicit hosting disconnect releases immediately on the next control
tick. Existing Session rules also release/fence on WebRTC loss, lease loss,
lifecycle shutdown, verification expiry and process shutdown. A late response
cannot revive a cancelled request, and queued frames cannot gain authority from
a later epoch. Video arrives as encoded frames with both timestamps through the
same operator interface, then is counted/discarded; video loss is independent
of the MAVLink connection and lease.

## Automated evidence

Host: native macOS ARM64. Baseline: committed `522bb8f7` plus the #166 worktree
changes. `tmp/issue-166/` retains build/test logs, the Just command check,
source hashes and completion audit. No commit is created automatically.

Verified on 2026-10-23: `just agent::test` passes **3/3 CTest targets**
(8.69 seconds: runtime 3.94 s, manual UDP 4.52 s, host 0.21 s) and **19 Python
checks** (0.858 s). The runtime output explicitly passes `real SDK manual UDP`;
the manual target passes all seven socket/lease groups. An actual
`just agent::run fixture <occupied-port> --control --region eu-central-1`
reuses the cached build without new compilation and exits with the intended
port remedy in 2.453 seconds, while both AWS profile paths point to blocking
FIFOs. Evidence: `tests-verified.log`, `ctest-last.log`,
`just-command-check.{log,json}` and `source-sha256.json`.

| Acceptance requirement | Authoritative checks |
| --- | --- |
| Foreground command, default/custom ports, useful argument/bind errors | `agent/justfile`, real `txing-agent` CLI tests, actual duplicate loopback bind; blocked AWS config/credential FIFOs establish bind-before-SDK behavior |
| Immediate telemetry and initial MAVLink 1 bootstrap | Real UDP receives telemetry before any uplink; generated valid MAVLink 1 heartbeat establishes presence before/after telemetry readiness and is never forwarded; subsequent MAVLink 2 parameter traffic works |
| Explicit free lease and full pre-arm traffic | Observation-only socket sends no board requests; control case checks `takeover=false`, parameter request before arm, and Office/peer-style `control_busy` without retries or displacement |
| Retention and release | Generated arm/disarm/re-arm frames preserve one lease; 4999/5000 ms presence boundary, closed client socket, cancelled pending grant, stale state/renewal epochs, WebRTC loss, REDCON loss, verification expiry and process shutdown |
| Signed/unfamiliar framing | Maximum-payload signed unknown frame round-trips unchanged; concatenated frames split byte-exactly; malformed flags/lengths, invalid MAVLink 1 CRC, valid prefix plus incomplete suffix, oversized/truncated datagrams and split signatures are rejected |
| Common operator/video independence | Real encoded H.264 and metadata reach ManualOperator over real SDK peers; video-only failure leaves parameter uplink and the lease working; existing bounded-video checks isolate slow consumption |
| Real transport integration and diagnostics | `real SDK manual UDP` exercises UDP → ManualOperator → Actions/Session → real ICE/DTLS/SCTP peers, signed downlink/uplink, H.264 and graceful release; accelerated monotonic-time check retains a specific failure after long healthy operation |

`just agent::test` covers the existing runtime, new manual UDP integration and
MicroVM host CTest targets, plus Python CLI, host-wire and shadow-contract checks.
The shadow test's obsolete eight-hour expectation is aligned with the already
approved 3000-second example; no schema or deployed shadow changes.

The manual tests model board lease replies but use actual OS sockets. The real
SDK check models only signaling exchange and board authorization; ICE, DTLS,
SCTP, H.264 packetization and callbacks are the pinned SDK. None of this is
physical acceptance or proof of GUI parameter negotiation on the TBot.

## Rollout and remaining gates

Run `just agent::test`, configure QGC's local/remote ports, then use the native
foreground command. Begin without `--control` to observe. Physical control and
parameter/GUI acceptance require the operator-run #167 procedure on a secured
lifted TBot. Stop the native command with Ctrl-C/SIGTERM and end it by fifty
minutes under the [current-stage session limit](constraints/agent-session-limit.md).
Board renewal can interrupt earlier; the adapter does not bypass lifecycle or
add an automatic native duration timer.

No board, rig or Office deployment, AWS change or firmware flashing is required.
The #165 immutable image remains the earlier accepted revision; a future cloud
release must rebuild/package this newer runtime. The probe source allowlist now
includes the existing pinned generated MAVLink headers, provenance and licenses
needed by the heartbeat check and tests. No new MicroVM is launched here.
Cloud attachment/controller/publication and all later issue implementation stay
outside #166.
