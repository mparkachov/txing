# Future Work

This document records backlog items and technical debt that should not block the
current implementation track, but should be kept visible for later cleanup or
larger dependency work.

## Rust Dependency Deduplication

### Scope

The dependency review covered the project-owned Rust lockfiles:

- `devices/power/test/Cargo.lock`
- `devices/unit/daemon/Cargo.lock`
- `devices/weather/test/Cargo.lock`
- `rig/Cargo.lock`

Vendored third-party lockfiles under the MCU SDK/vendor tree are intentionally
out of scope. They are not actionable repository dependencies.

### Summary

Several lockfiles contain multiple versions of the same transitive packages.
Most duplication comes from upstream AWS SDK, Smithy, TLS, MQTT, and
cross-platform target dependency stacks. A broad cleanup would be high churn and
would not materially improve the current unit daemon runtime work.

The visible `release::bump` update notes are also not all direct upgrade
opportunities:

- `generic-array 0.14.7` cannot be moved to `0.14.9` locally because
  `crypto-common 0.1.7` pins `generic-array = "=0.14.7"`.
- `reqwest 0.12 -> 0.13` is a direct dependency migration, not a lockfile-only
  update.
- Go Lambda modules are out of scope for this Rust lockfile review.

### Decision Matrix

| Area | Duplicate versions | Seen in | Main cause | Decision |
| --- | --- | --- | --- | --- |
| AWS HTTP/TLS stack | `http 0.2/1`, `http-body 0.4/1`, `hyper 0.14/1`, `h2 0.3/0.4`, `hyper-rustls 0.24/0.27`, `rustls 0.21/0.23`, `tokio-rustls 0.24/0.26` | Unit daemon, rig | AWS SDK and Smithy currently carry both older and newer HTTP/TLS stacks | Defer. Do not chase with local overrides. Revisit when upgrading AWS SDK/Smithy or replacing a larger AWS client surface. |
| RustCrypto stack | `block-buffer 0.10/0.12`, `crypto-common 0.1/0.2`, `digest 0.10/0.11`, `cpufeatures 0.2/0.3` | AWS-heavy Rust projects | `aws-config -> sha1 0.10` keeps old `digest/crypto-common`; newer AWS signing code uses newer traits | Defer. Local bump is blocked by upstream pins, including `generic-array = "=0.14.7"`. |
| `reqwest` | Direct use is still `0.12`; `0.13` is available | Unit daemon | Direct dependency version, with changed feature names and TLS behavior | Separate migration task. Requires daemon IoT/TLS testing. |
| Randomness stack | `rand 0.8/0.9/0.10`, `rand_core 0.6/0.9/0.10`, `rand_chacha 0.3/0.9`, `getrandom 0.2/0.3/0.4` | Unit daemon, rig | Transitive `gneiss-mqtt`, `tungstenite`, AWS, UUID, and BLE dependencies | Defer. Do not expect direct local changes to remove all duplicate `rand` versions. |
| Platform target crates | `windows-sys`, `windows-targets`, Windows target crates, `core-foundation`, `security-framework`, `rustls-native-certs`, `openssl-probe` | Cross-platform lockfiles | Cargo locks include non-Linux target dependencies | Ignore for Raspberry Pi/Linux `aarch64` work unless those targets become release targets. |
| Java/native test deps | `jni-sys 0.3/0.4`, `thiserror 1/2` | Power/weather tests, rig | Target-specific/native transitive dependencies; older WebSocket stack also keeps `thiserror 1` | Defer. Not on the unit daemon runtime path. |
| Utility/data crates | `hashbrown 0.14/0.15/0.17`, `itertools 0.13/0.14` | Unit daemon, rig | Normal transitive ecosystem drift | Ignore unless touching the direct caller or an upstream update removes the duplicate naturally. |

### Candidate Follow-Up Tasks

1. Evaluate `reqwest 0.13` separately for `devices/unit/daemon`. This needs
   focused testing because TLS feature names and behavior changed.
2. Periodically check whether AWS SDK, Smithy, `gneiss-mqtt`, or `tungstenite`
   updates collapse the duplicate HTTP/TLS and RustCrypto stacks.
3. Keep platform-target duplicate crates out of Linux `aarch64` decisions unless
   the release matrix expands.

### Non-Actions

- Do not add local dependency overrides for AWS, Smithy, RustCrypto, TLS, or
  platform crates just to reduce duplicate rows in `cargo tree -d`.
- Do not treat `generic-array 0.14.9` as a normal patch update until the
  upstream exact pin is gone.
- Do not combine `reqwest 0.13` migration with release or daemon deployment
  changes; it deserves its own test cycle.

## Rig Deploy Credentials

Rig deployment is operator-side. The rig host keeps only the Greengrass
certificate/private key and does not store AWS access keys for deployment.

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

Current non-actions:

- do not add a second KVS channel to the current `unit` path
- do not add a cloud session consumer until there is a concrete product use
  case
- do not change the active-control protocol for this future work; reuse
  `control.activate`, `takeover`, session identity, transport, and epoch
  enforcement unless a real protocol gap is found
