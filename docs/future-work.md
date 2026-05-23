# Future Work

This document records backlog items and technical debt that should not block the
current implementation track, but should be kept visible for later cleanup or
larger dependency work.

## Rust Dependency Deduplication

### Scope

The dependency review covered the project-owned Rust lockfiles that remain
active:

- `devices/power/test/Cargo.lock`
- `devices/weather/test/Cargo.lock`

The retired Rust `devices/unit/daemon` lockfile was removed when the unit board
daemon build surface moved fully to Go.

Vendored third-party lockfiles under the MCU SDK/vendor tree are intentionally
out of scope. They are not actionable repository dependencies.

### Summary

Several lockfiles contain multiple versions of the same transitive packages.
Most duplication comes from upstream TLS, native test, and cross-platform target
dependency stacks. A broad cleanup would be high churn and would not materially
improve the current device test work.

The visible `release::bump` update notes are also not all direct upgrade
opportunities:

- `generic-array 0.14.7` cannot be moved to `0.14.9` locally because
  `crypto-common 0.1.7` pins `generic-array = "=0.14.7"`.
- Go Lambda modules are out of scope for this Rust lockfile review.

### Decision Matrix

| Area | Duplicate versions | Seen in | Main cause | Decision |
| --- | --- | --- | --- | --- |
| RustCrypto stack | `block-buffer 0.10/0.12`, `crypto-common 0.1/0.2`, `digest 0.10/0.11`, `cpufeatures 0.2/0.3` | Rust device tests | Native and crypto-related transitive dependencies | Defer. Local bump is blocked by upstream pins, including `generic-array = "=0.14.7"`. |
| Platform target crates | `windows-sys`, `windows-targets`, Windows target crates, `core-foundation`, `security-framework`, `rustls-native-certs`, `openssl-probe` | Cross-platform lockfiles | Cargo locks include non-Linux target dependencies | Ignore for Raspberry Pi/Linux `aarch64` work unless those targets become release targets. |
| Java/native test deps | `jni-sys 0.3/0.4`, `thiserror 1/2` | Power/weather tests | Target-specific/native transitive dependencies; older WebSocket stack also keeps `thiserror 1` | Defer. Not on the unit daemon runtime path. |
| Utility/data crates | `hashbrown 0.14/0.15/0.17`, `itertools 0.13/0.14` | Rust device tests | Normal transitive ecosystem drift | Ignore unless touching the direct caller or an upstream update removes the duplicate naturally. |

### Candidate Follow-Up Tasks

1. Periodically check whether upstream dependency updates collapse duplicate
   RustCrypto stacks.
2. Keep platform-target duplicate crates out of Linux `aarch64` decisions unless
   the release matrix expands.

### Deferred Boundaries

These cleanup paths remain out of scope for the current implementation track:

- local dependency overrides for AWS, Smithy, RustCrypto, TLS, or platform
  crates just to reduce duplicate rows in `cargo tree -d`
- treating `generic-array 0.14.9` as a normal patch update before the upstream
  exact pin is gone

## Rig Host Credentials

The standalone rig host keeps only its IoT certificate/private key and does not
store AWS access keys.

## Cloud And Control-Only RTC Consumers

The current unit implementation uses one AWS KVS media session for browser
video and MCP control at REDCON `1`, and MQTT MCP at REDCON `2` when video is
unavailable or not ready. That path is complete for the current browser
operator workflow.

Future work may add non-browser session consumers:

- a cloud worker that connects as another MCP session and uses the existing
  `control.activate` takeover semantics
- a no-video or control-only WebRTC worker for device types where MCP should
  use WebRTC without a media track
- a distinct KVS signaling channel for a control-only WebRTC path, if a future
  device needs it
- admission, scheduling, or policy around cloud workers competing with human
  operators for the single active-control slot

Out of scope for the current unit operator path:

- a second KVS channel for the current `unit` path
- a cloud session consumer before there is a concrete product use case
- active-control protocol changes for this future work unless a real protocol
  gap is found
