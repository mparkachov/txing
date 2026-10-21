# Native agent acceptance — #164

Status: native macOS active observation and acceptance checks passed on
2026-10-21 against `tbot-8yzfgj` at actual REDCON 1. Both real streams reached the
production operator; separate live fault injection verified independent peer
recovery, video-only lifecycle gating and the verification deadline. The device
was never controlled or reconfigured. Limits below distinguish test injection
from physical state changes and static credentials from live provider refresh.

## Active macOS evidence — 2026-10-21

The same macOS ARM64 host and dependency versions listed in the historical
record below ran the current uncommitted source. The Mac cache is now restored
to `tmp/agent-build/`; Linux is preserved at `tmp/agent-build-linux-issue164/`.
The application remains shared C++ source intended for both hosts. The current
SDK patch, live test and negotiation diagnostics have not been rerun on Linux;
the earlier Linux results apply to the source recorded on 2026-10-20.

### Signaling defect and bounded correction

Initial active startup authenticated to AWS, fetched TURN configuration and
opened signaling, but both offer writes timed out with `0x0000000f`
(`STATUS_OPERATION_TIMED_OUT`). The pinned SDK requested writable callbacks
from a sending thread. On the native libwebsockets 5.0 build, merely adding a
service wakeup after that request still failed. Instrumented callback reasons
showed the wakeup event arriving without the requested writable callback.

`agent/cmake/kvs-lws-event-loop.patch` stores the signaling owner on its LWS
context, uses `lws_cancel_service` from the sending thread, and requests the
writable callback on the service thread's `LWS_CALLBACK_EVENT_WAIT_CANCELLED`.
The explicit CMake step checks the existing KVS commit, applies idempotently to
the private agent dependency checkout, and rejects mismatched source. The shared
SDK pin and shared build resources are unchanged. CMake 3.27+ connects the step
to `patch_disconnected` so normal cached builds do not force SDK updates.
Temporary callback instrumentation was removed before final validation.
Negotiation errors now retain whether an offer is awaiting an answer or an
answer has reached ICE/DTLS negotiation; successful connection events clear old
failure text. No SDP, tokens or TURN secrets are logged.

### Observations and live faults

- A real foreground `just agent::run tbot-8yzfgj --region eu-central-1` resolved
  registered type `tbot` and received both streams through AWS signaling and
  native ICE/DTLS/SRTP/SCTP. Its first H.264 frame carried 35,304 encoded bytes,
  presentation timestamp `314469310000` in 100 ns ticks and receipt timestamp
  `1792566065272` in Unix ms. Counts increased to 5,233 telemetry messages and
  8,481 video frames before Ctrl-C; 176 video frames were dropped by the bounded
  consumer. The application reported `agent stopped: process signal` (the Just
  terminal group returned 130).
- The separate `agent-live-tests` executable uses the production session,
  transport and SDK with the actual AWS lifecycle reader. It injects faults
  only in its own process. A complete run exited 0: real streams/metadata;
  video-peer loss/recovery with telemetry continuing; telemetry-peer
  loss/recovery with video continuing; lifecycle 1/2/1 override closing and
  reopening only video; and lifecycle-read failures stopping the session at
  verification age **15,045 ms**. No authority was acquired and no MAVLink
  action was sent.
- Intermittent unanswered offers exercised the twenty-second negotiation
  deadline and bounded retry. One early live recovery run exhausted its
  forty-second test window. The diagnostic run recovered each stream after a
  retry without restarting the other stream, and completed all phases.
- The operator-provided board log identifies `txing-board-kvs-master 0.18.2`.
  It shows successful ICE/DTLS/data-channel opening followed by signaling-write
  timeouts (`writeLwsData` / `signalingSendMessageSync`, `0x0000000f`) while
  handling replacement peers. This supports the missing-answer diagnosis;
  the exact board-side cause is not proven by this log. TURN candidate errors
  also occur around successful connections. The agent patch does not update
  the deployed board. Board reliability work is separate from this issue.
- Office's public REDCON 2 request reported `redconCommandStatus=succeeded`,
  target 2, while actual REDCON remained 1. Capability-derived readiness is
  authoritative; public commands 1/2/3 share the MCU wake mapping and Office
  treats actual 1 as satisfying target 2. See
  [TBot mapping](../devices/tbot/README.md) and
  [lifecycle convergence](sparkplug-lifecycle.md). No physical 1/2/1 transition
  is claimed. The process-local override above verifies agent policy with real
  peers while the actual device stays at 1; death/inactive policies also have
  deterministic coverage and the prior real inactive startup below.
- The selected `mayor` provider is a static profile without a session token,
  role, credential process or SSO configuration. Real IoT and KVS calls work
  through that profile. There is no expiring tuple to refresh; rotating,
  expired and failing providers pass automated adapter tests. No live SSO or
  role-credential refresh is claimed.
- A final direct production run from 07:22:03 to 07:22:34 UTC received 483
  telemetry messages and 685 video frames (six bounded-queue drops). Its first
  frame had 21,741 encoded bytes, H.264 codec, presentation timestamp
  `1450531380000` and receipt timestamp `1792567327566`. SIGTERM produced
  `agent stopped: process signal` and exit **0**; cleanup finished in 226 ms.
- Final native build and tests passed: ten C++ runtime groups including real
  SDK peers, plus ten shadow contract tests. A repeated cached build reused
  all **642** object files with unchanged modification times and sizes.

Scratch evidence is under `tmp/agent-native-evidence/live-2026-10-21/`:
`event-thread-experiment.log`, `live-recovery.log` (initial failure),
`live-recovery-diagnostic.log` (all phases pass), `operator-board-kvs.log`,
`foreground-sigterm*`, `final-build*`, `final-cache-result.json`,
`final-tests.log`, `patch-check.log`, lifecycle/descriptor snapshots,
`provider-kind.json`, and final source/archive/hash provenance. These local
files are not committed; this document and #164 record the durable results.

## Native macOS evidence — 2026-10-20

Validated on macOS 27.0.1 (26A434), Darwin 27.0.0 arm64, starting from
`9d4eff7cb2d6` plus the uncommitted #164 source. Application C++ source is
unchanged from the Linux validation; this native continuation changes only the
agent CMake dependency selection and this evidence record.

- A fresh `just agent::build` used the default SDK download and Homebrew
  dependency discovery paths, without a source override. It reproduced an
  undefined `OPENSSL_sk_set_thunks` link failure: AWS CRT's `aws-c-io` imported
  Homebrew's AWS-LC-based s2n instead of the SDK's already-built pinned s2n.
  `agent/CMakeLists.txt` now disables optional installed-s2n discovery, using
  the pinned in-tree target with the same OpenSSL as KVS. Reconfiguration with
  `just agent::build -DCMAKE_BUILD_TYPE=RelWithDebInfo` passed. The resulting
  executable is native Mach-O ARM64, links repository `lib/libs2n.a`, and runs
  `--help`. No upstream SDK or shared KVS build files were changed.
- A subsequent plain `just agent::build` passed and reused all 641 compiled
  objects, with object modification times and sizes unchanged.
- `just agent::test` passed: all ten C++ runtime groups (CTest, 8.49 seconds)
  and ten shadow contract tests. Native tests include real SDK ICE/DTLS/SRTP/
  SCTP peers, H.264/telemetry receipt, a substitute operator's authorized signed
  action and release, continued telemetry after video teardown, credential
  providers/rotation/errors, lifecycle deadlines, bounded queues, and the
  queued-authority regression. Local peers do not exercise AWS signaling/TURN.
- `just agent::trust` passed. Replacing cached CA1 with the valid but different
  CA2 was rejected; restoring CA1 made verification pass again. All five roots
  passed the recipe's hash and expiry checks.
- `just agent::run tbot-8yzfgj --region eu-central-1` ran in the foreground
  using the existing `mayor` SDK profile (no environment key/token). It resolved
  registered type `tbot`, read the real Sparkplug shadow through the discovered
  Data-ATS endpoint, reported zero observations and exited successfully with
  `agent stopped: device inactive or dead`. The shadow reported `DDEATH`.
  This verifies native profile authentication, read-only IoT APIs, TLS and
  inactive shutdown, without opening device sessions or acquiring control.
- CLI help, Just parsing and `git diff --check` passed. No commits, AWS resource
  mutations, board changes, physical control or firmware flashing were performed.

Native dependencies: Apple Clang 21.0.0 (clang-2100.3.34.2), CMake 4.4.4,
Just 1.59.0, OpenSSL 3.5.9, libwebsockets 5.0.0_2, srtp 2.8.1_1,
libusrsctp 0.9.5.0_1, log4cplus 2.2.0.1, system libcurl headers 8.7.1.
Both checkout revisions were verified: AWS SDK 1.11.913 at
`269ff2277f247d78526414b5052729844532362e` and KVS at
`bb106510cf74edd2c24881c1ae94ceaa0083d15c`.

Scratch evidence is under `tmp/agent-native-evidence/`: `build-before-fix.log`,
`build.log`, `build-cached.log`, `cache-result.txt`, `tests.log`,
`runtime-details.log`, `trust*.log`, `inactive-observation.log`, host/dependency/
pin records, link commands, source patches, source archives and SHA-256 manifests.
The final source archive includes the untracked agent implementation. These
scratch files are not committed; this document and the #164 comment are the
durable results. No credentials, tokens, complete AWS configuration, SDP or
TURN secrets belong in evidence.

After returning to Linux, the Mac cache was preserved at
`tmp/agent-build-macos-issue164/` and the saved Linux cache was restored from
`tmp/agent-build-linux-issue164/` to `tmp/agent-build/`. CMake caches are
host-specific and contain absolute paths: preserve the current host's cache
and restore the desired host's cache to its original `tmp/agent-build/` path
before switching hosts. Do not run the saved Mac cache from its relocated path.

At the end of this 2026-10-20 session, active AWS/TBot acceptance remained
pending. The 2026-10-21 record above supersedes that status.

## Required operator record

On the development Mac, manually install the prerequisites described in
[agent/README.md](../agent/README.md), configure the authorized AWS SDK profile,
and activate an existing registered TBot through the normal operator flow.
This run is observation only; physical driving acceptance is #167.

Run and preserve output (replace the Thing ID and profile):

```sh
mkdir -p tmp/agent-native-evidence
uname -srm > tmp/agent-native-evidence/host.txt
git rev-parse HEAD > tmp/agent-native-evidence/revision.txt
git diff --binary > tmp/agent-native-evidence/source.patch
git ls-files --others --exclude-standard > tmp/agent-native-evidence/untracked.txt
just agent::build > tmp/agent-native-evidence/build.log 2>&1
just agent::test > tmp/agent-native-evidence/tests.log 2>&1
AWS_PROFILE=<profile> just agent::run <thing-id> --region eu-central-1 \
    2> tmp/agent-native-evidence/observation.log
```

The source patch excludes untracked files. Preserve their contents or commit the
reviewed source manually before testing; record enough provenance to reproduce
the tested source. Record native dependency versions and the KVS pin alongside
the AWS SDK commit printed/verified by the build. Never include credentials,
session tokens, complete AWS config files or SDP/TURN secrets in evidence.

Record registered Thing type `tbot`, both sessions opening at born REDCON 1,
increasing telemetry/video counts without an operator attachment, and encoded
video codec/presentation/receipt metadata at the operator. If the actual
projected lifecycle changes from 1 to 2 and back, only video should close/reopen
while telemetry continues. A command requesting 2 can be satisfied by actual 1;
do not treat that request as a physical transition. The explicit
`agent-live-tests <thing-id> <region> <verified-ca-pem>` executable tests
peer loss, lifecycle overrides and verification failure inside its own process
using real connections; it never writes device state. Distinguish those injected
faults from actual lifecycle changes. Record inactivity/death and signal shutdown
from native runs or deterministic coverage, and distinguish credential adapter
rotation tests from live refresh by an expiring selected provider. Include
timestamps and any errors. No native acceptance
claim can be made from an ELF binary or an ARM64 cross-build.

The automated real-peer test must consume both observations and send an
explicitly authorized action through the production operator interface. This
proves substitution without model inference, a plugin system, or a second
production transport. Live observation must use the same C++ application source
as the Linux ARM64 build. Local operation must not write the agent shadow or
invoke the future cloud controller.

## Evidence from the Linux implementation environment

Validated 2026-10-20 on Linux 7.0.0-38-generic aarch64, starting from
`9d4eff7c` with the uncommitted #164 source. The executable is an ELF ARM64
binary, not a native Mac artifact. That Linux run did not perform live AWS,
macOS, physical-device or cloud-probe acceptance.

- `just agent::build` passed; `txing-agent --help` ran. The build uses one
  executable with direct KVS/AWS SDK linkage. A subsequent cached build reused
  the SDK and application objects.
- `just agent::test` passed: ten C++ runtime test groups (including actual SDK
  peers) and ten Python shadow contract tests. The real-peer test received
  encoded H.264/telemetry, granted control to a substitute operator, preserved
  its signed/unfamiliar MAVLink action, released the lease, and proved telemetry
  survives destruction of the video peers.
- Tests verify independent recovery and slow cleanup, two-second polling,
  fifteen-second verification expiry, death/inactive exit, control contention,
  epochs, inactivity, lease/request loss, explicit release/shutdown, and bounded
  video overload while telemetry/control continue.
- Credential tests use actual AWS SDK profile/environment/static/temporary
  providers in repository scratch plus a rotating/expired/throwing provider
  through the KVS adapter. No real provider login or remote refresh was tested.
- All five downloaded TLS roots passed published hash/expiry verification.
  Substituting another valid root into the cached CA1 file was rejected; the
  original root was restored and verification passed again.
- Just parsing, POSIX shell syntax, `git diff --check`, and CLI help passed.
  Changes are limited to `agent/` and agent documentation; board/rig/Office,
  shared SDK resources, deployed wire protocols and infrastructure are unchanged.

The host lacked development libraries. Validation extracted Ubuntu development
packages into `tmp/issue-164/deps/` without installing host packages, and used
`tmp/issue-164/build-env.sh` to supply that prefix. The AWS SDK source override
was `tmp/issue-164/aws-sdk-cpp/`, cloned recursively at the pinned release/commit.
The native results above verify the default Mac dependency
discovery/download path, with the documented s2n selection correction.
Native library versions: OpenSSL 3.5.5, libwebsockets 4.3.5, libsrtp2 2.7.0,
libusrsctp 0.9.5.0, log4cplus 2.0.8, libcurl 8.18.0; GCC 15.2.0 and CMake 4.2.3.
AWS SDK: 1.11.913 (`269ff2277f247d78526414b5052729844532362e`). KVS SDK:
`bb106510cf74edd2c24881c1ae94ceaa0083d15c` (the existing shared pin).

Scratch evidence: `tmp/issue-164/full-tests.log`,
`tmp/agent-build/Testing/Temporary/LastTest.log`, build logs, and
`tmp/issue-164/trust-reject.log`. These files are not committed; the results and
limits above are the durable record.

A continuation audit reproduced an authorization race: a frame submitted while
the acquisition reply was pending reached the transport after the reply granted
control. The regression failed on the prior source
(`tmp/issue-164/authority-before.log`). The session now rejects sends without a
current grant and fences queued frames to the grant's local generation.
Regression coverage includes pre-grant submission, takeover before dispatch,
and explicit reacquisition at a new epoch. The complete suite passes with this
coverage (`tmp/issue-164/authority-after.log`). Native/live evidence was absent
at that point. The 2026-10-21 active record above supersedes this historical
validation limit.

### Linux rerun after the native CMake fix

On 2026-10-20, the saved Linux cache was restored to `tmp/agent-build/` and
the native Mac cache preserved at `tmp/agent-build-macos-issue164/`.
`just agent::build` regenerated CMake with installed-s2n discovery disabled and
passed. The link command uses repository `lib/libs2n.a` and the existing Linux
OpenSSL libraries. The application is ELF ARM64 and runs `--help`; the preserved
Mac application remains Mach-O ARM64.

`just agent::test` then passed all ten C++ runtime groups (2.69 seconds) and ten
shadow contract tests. Its build dependency reused the compiled objects.
SHA-256 verification confirmed that all 14 application/header/test/CMake/Just
source files match the final macOS evidence manifest; no application source
changed between host validations. `git diff --check` passed.

Evidence is in `tmp/issue-164/linux-resume/`: `build.log`, `tests.log`,
`help.log`, and `source-identity.txt`. The same repository-local Linux dependency
prefix and AWS source override described above were used. This rerun verifies
the native linking correction on Linux. Active AWS/TBot observation was still
pending on 2026-10-20 and is now recorded above.

## Requirement audit

| #164 criterion | Current evidence | Status |
| --- | --- | --- |
| Build/cache and actual macOS foreground observation from shared source | Native Mach-O foreground run received increasing real telemetry/video; shared source; cached builds verified | Native live verified |
| One process, direct pinned SDK, one process-owned initialization | `main.cpp`, `credentials.cpp`, `kvs.cpp`, `peer.cpp`; linked executable and real peers | Implemented/automated |
| Registered type/profile before sessions; explicit generic transport configuration | Native AWS lookup resolved `tbot`; both actual channels opened; profile/peer tests match the manifest | Native live/automated verified |
| REDCON activation, independent recovery, timers, inactivity/death, shutdown | Real-stream independent peer recovery and injected lifecycle/15,045 ms verification timeout; deterministic death/inactivity; real inactive and signal shutdown | Native live/automated verified; physical REDCON transition not claimed |
| Encoded video/codec/timestamps before count/discard; bounded consumers | Production real H.264 frame metadata and increasing counts; queue drops and overload tests | Native live/automated verified |
| Substitute test operator observes both and sends an authorized action | Real SDK peer test through the same `Session`/`Actions` interface | Automated verified |
| SDK credentials/refresh, prerequisites, verified TLS, no local cloud writes | Real static-profile IoT/KVS calls; rotating/expired provider adapter tests; trust verification/rejection | Native live/automated verified; no expiring live provider selected |
| Real peers, failure/loss/substitution and native macOS evidence recorded | All ten C++ groups and ten contract tests pass; Mach-O foreground active run and real-stream fault acceptance recorded | Recorded |

Local rollout: build/test with the updated agent source and use the existing
authorized SDK profile, then run `just agent::run <thing-id> --region eu-central-1`.
No cloud deployment, publication, board update or firmware flashing is needed.
On returning to Linux, preserve the Mac cache, restore the Linux cache to its
original `tmp/agent-build/` path, then rerun build/tests for the new SDK patch
and diagnostics. Do not run a relocated host cache in place. All source remains
uncommitted. Stop at #164; the cloud probe and physical control belong to later
issues with their own operator gates.
