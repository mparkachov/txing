# Native physical acceptance — #167

Status, 2026-10-27: **open**. Run 16 passes the complete manual flow, and run 20
verifies held-lease release on real credential expiry. On operator-installed
KVS 0.18.5, cases 25/26 now pass real camera-only isolation, stable actual
REDCON 1→2 and fresh MAVLink-only entry at actual 2 with parameter retrieval.
Camera recovery through an operator 4→1 power cycle restores video/MAVLink.
The subsequent fifteen-minute disarmed case 27 completes without a recurrence
and releases its held lease. Office then fails two explicit control attempts
with `control.activate` timeouts. Required human takeover remains a blocking
acceptance condition; Office 0.18.3 client recovery/policy changes are prepared
but require manual deployment and a real handoff retest. Earlier intermittent
transport timeouts remain unexplained. Board-side timing diagnostics are
prepared as 0.18.6. These new changes remain uncommitted; earlier cases and
their exact tested versions remain recorded below.
This record covers the actual development Mac, QGroundControl
and secured lifted TBot. Automated checks and process-injected faults support
diagnosis but do not replace the physical evidence required by #167.

## Test identity and preparation

- Source: `74c5e4d1519518aee53e26af03feab47153203da` (#166), clean at start.
- Host: macOS 27.0.1, native ARM64.
- AWS C++ SDK: 1.11.913, commit
  `269ff2277f247d78526414b5052729844532362e`.
- KVS SDK pin: `bb106510cf74edd2c24881c1ae94ceaa0083d15c`, with the existing
  agent-private event-loop patch. No shared SDK change.
- Native dependencies: OpenSSL 3.5.9, libwebsockets 5.0.0_2, srtp 2.8.1_1,
  libusrsctp 0.9.5.0_1, log4cplus 2.2.1. Preserve the built executable SHA-256
  and linked-library listing with each tested revision.
- Device: `tbot-8yzfgj`, registered type `tbot`, region `eu-central-1`.
- Operator confirmed that the TBot is secured/lifted, wheels clear and initially
  disarmed. QGroundControl version: **v5.1.5 64-bit**, operator-reported.
- Operator confirmed the requested QGC setup: UDP listener 14550, remote
  `127.0.0.1:14551`, heartbeat emission enabled. The OS socket check subsequently
  shows QGC bound to 14550 and the agent receives valid client datagrams.
- Preparation: `just agent::test` passes 3/3 native CTest targets and 19 Python
  checks. This establishes the local baseline, not physical acceptance.

Evidence directory: `tmp/issue-167/`. Starting files include
`source-host-preflight.json`, `preflight-tests.log`, `read-only-preflight.json`
and the raw preflight shadow responses. These scratch files remain local.
No credentials, session tokens, SDP or TURN secrets belong in the record.

The 08:25 UTC preflight projection reports DBIRTH/REDCON 4 and unavailable
board/MAVLink/video capabilities. The separate MAVLink shadow has cached domain
fields (`armed=false`, no active control); those fields do not override the
authoritative lifecycle/capability projection or prove a live board link.
The `agent` named shadow is absent. No agent or control run was started by this
preflight. The subsequent operator activation and real observations below
supersede that initial inactive state.

## QGroundControl v5.1.5 setup

Open **Application Settings → Comm Links**. In **AutoConnect**, turn off
**Automatically open a connection over UDP** so the manual link is the only
QGC listener on 14550. In **Links**, click **Add** and enter:

| Field | Value |
| --- | --- |
| Name | `TBot Agent` |
| Type | `UDP` |
| Port | `14550` (QGC's local listening port) |
| Server Addresses (optional) | `127.0.0.1:14551`, then click **Add Server** |
| Automatically Connect on Start | Off for this test |
| High Latency | Off |

Click **Save**, then **Connect** beside `TBot Agent`. Under **Application
Settings → Telemetry → Ground Station**, leave **Emit heartbeat** enabled.
The agent's listener is 14551; QGC's listener is 14550. Configure the link here,
separately from the MAVLink Forwarding settings.

These names are verified against the v5.1.5
[link editor](https://github.com/mavlink/qgroundcontrol/blob/v5.1.5/src/AppSettings/LinkConfigurationManager.qml),
[UDP fields](https://github.com/mavlink/qgroundcontrol/blob/v5.1.5/src/AppSettings/UdpSettings.qml),
[Comm Links page](https://github.com/mavlink/qgroundcontrol/blob/v5.1.5/src/AppSettings/pages/CommLinks.SettingsUI.json)
and [Telemetry settings](https://github.com/mavlink/qgroundcontrol/blob/v5.1.5/src/AppSettings/pages/Telemetry.SettingsUI.json).
The operator subsequently confirmed configuration and the observed UDP socket
and native client counters confirm the active port mapping.

## First actual runs — 2026-10-25

The operator selected REDCON 1. Read-only inspection at 08:34 UTC confirms actual
DDATA/1, available board/MAVLink/video capabilities, disarmed state and no active
lease. The recorded executable hash still matches the native preflight.

The view-only command (`01-observation.log`) receives **7,757 telemetry messages
and 13,454 encoded video frames**, with 10,835 valid QGC datagrams, zero rejected
UDP datagrams and no control grant. The first H.264 observation has 42,978 bytes,
presentation timestamp 209595570000 in 100 ns ticks and receipt Unix ms
1792917310410. The bounded video queue reports 42 drops; those are queue drops,
separate from SDK frame-drop warnings. The operator sees increasing QGC Link
Status sent/received counters, live EKF text, and Not Ready / Manual in Fly View,
but does not report changing numeric telemetry widgets. The board sample shows
two peers, both observers, and disarmed state. Ctrl-C ends this run with
`agent stopped: process signal`; the Just terminal group exits 130.

The explicit control command (`02-control.log`) then acquires a free board
lease: actor `QGroundControl`, session `mavlink-3`, epoch 1. Read-only samples
record that owner and disarmed state. The operator reports that parameter names
and values load after **Vehicle Setup → Parameters → Tools → Refresh**. QGC
also displays a missing-parameter warning for `RCMAP_ROLL`, `RCMAP_PITCH`,
`RCMAP_YAW`, `RCMAP_THROTTLE`, `RC0_MIN`, `RC0_MAX`, `RC0_TRIM`; that warning's
cause/resolution is not established by loading a list. Repeated EKF3 IMU0 forced
reset/initialised messages are also unresolved. The tracked TBot configuration
uses a synthetic IMU, but this is not verification of the deployed firmware or
an explanation of these messages. No parameter/configuration repair is applied.

Both media counters stop at **15,666 telemetry / 6,906 video**. The native log
first records `control=0 control request timed out`, then retires telemetry
after fifteen seconds without valid MAVLink. Video subsequently loses WebRTC;
repeated new offers receive no answer. All subsequent native control reports
remain false; there is no reacquisition. The operator reports actual REDCON 3
and an unpingable device, and identifies this as the same behavior as #171.

The actual Sparkplug REDCON field changes to 3 at **08:49:44 UTC / 09:49:44 CET**,
with board/MAVLink/video capabilities unavailable and target still 1. The native
process exits 0 with `agent stopped: device inactive or dead`. The final agent
shadow read still returns ResourceNotFound. Both native runs and the two finite
read-only recorders have ended; no local agent remains listening on 14551.

The last MAVLink domain shadow is still version 986 and retains the old owner
and `armed=false`; those cached fields do **not** establish actual board-side
lease expiry/disarm after the outage. Native authority revocation, lack of
automatic reacquisition and real REDCON 3 shutdown are recorded. No physical
arm/drive/disarm/re-arm attempt occurred, and no board-side release-on-loss
claim is made from stale state.

This is a **suspected recurrence of #171's board networking outage**, not proof
of a new BCM2835 DMA kernel Oops: no kernel capture from this occurrence is
available. #171 remains separate from the selected #167 work. The operator is
performing the normal Office REDCON 4 → 1 recovery and has directed continuation
of #167. Verify actual REDCON 1, fresh board state and a free lease before the
next control run; do not reuse the interrupted run as complete control-flow
acceptance.

Evidence: `01-observation-{result,connected-summary}.json`,
`02-control-interrupted-result.json`, both native logs, both
`*-shadow-samples.jsonl` captures with raw field metadata,
`02-loss-shadow-summary.json`, `02-final-agent-shadow-result.json` and
`qgc-missing-rc-parameters.png` under `tmp/issue-167/`.

## Recovered control run — interrupted again

The operator completes the normal Office REDCON 4 → 1 recovery. Ping succeeds,
actual REDCON 1 and all required capabilities return, and MAVLink shadow version
991 replaces the stale pre-outage state with disarmed/unowned status. The
operator selects virtual joysticks and confirms **Virtual Joystick** and
**Auto-Center Throttle** on, **Left-Handed Mode** off, in QGC's Fly View settings.

`03-control.log` runs the unchanged native binary with `--control`. Both streams
open and the board grants actor `QGroundControl`, session `mavlink-2`, epoch 1.
The operator is asked to refresh parameters in this session and make an ordinary
Arm attempt with neutral controls and Allow Force Arm off. No arm transition is
captured in the read-only samples. The operator subsequently confirms that no
Arm attempt took place in this run.

Media freezes at **8,610 telemetry messages / 4,011 video frames**. Again the
native log revokes authority with `control request timed out`, retires silent
telemetry, loses video and receives no answers to repeated new offers. There is
one grant and one revocation, with no reacquisition. Native UDP traffic continues
to 7,805 accepted datagrams, with zero rejected/enqueue-send drops, so incoming
QGC activity alone is not being treated as restored board authority.

The read-only sampler captures actual DDATA/REDCON 3 by **09:07:12 UTC /
10:07:12 CET**, still with command sequence 130919 and target 1. This is not a
new operator request for 3. The native process exits 0 with `device inactive or
dead`. Both the agent process and its finite 64-sample recorder are terminal.
The MAVLink shadow remains version 993 with the old owner/disarmed fields;
actual post-outage board lease/arm state is unverified. There is still no kernel
capture establishing the cause of this second interruption.

Evidence: `03-control-{start,shadow-samples}.json*`, `03-control.log`,
`03-interrupted-result.json` and `03-final-{sparkplug,mavlink}.json`. Physical
arm/drive/disarm/re-arm and the remaining fault checks stay open. Repeating the
native automated tests cannot resolve the unavailable board or replace those
observations.

At 09:13:51 UTC the board answers ping, and a 09:14:57 UTC read reports actual
REDCON 1 under a new operator command (`dcmd-tbot-8yzfgj-19`, sequence 131237).
This later reachability is after another command/recovery sequence; it does not
show that networking was reachable during the second interruption.

## Ordinary arm recorded — connection lost again

Fresh preflight at 09:18:18 UTC reports actual REDCON 1 and MAVLink version 998,
disarmed/unowned. `04-control.log` starts at 09:19:26 UTC using the same native
executable hash. The board grants actor `QGroundControl`, session `mavlink-2`,
epoch 1. Session IDs can repeat after board recovery; this is a new run.

The operator reports **QGC shows Armed; sticks are centered**. At 09:20:48 UTC,
MAVLink shadow version 1001 confirms `armed=true`, Manual and the same lease.
The operator also supplies flight-controller text identifying ArduRover
V4.8.0-dev (`a04e2c93`), alongside the repeated EKF reset/initialisation messages.
This is an operator-reported firmware identity, not a deployed binary hash.

The next requested operator action is a brief forward input, return to center
and ordinary Disarm. Its physical outcome is not reported. Media then freezes
at **11,778 telemetry messages / 5,266 video frames**. The native log revokes
control on `control request timed out`, never reacquires, and exits 0 with
`device inactive or dead`. The final read-only sample at 09:24:32 UTC records
actual REDCON 3, unavailable board/MAVLink/video capabilities and unchanged
target 1. MAVLink version 1001 retains the old armed/owner fields, so neither
post-outage disarm nor actual board lease expiry is inferred from it.

The operator is immediately instructed to release the sticks, check the tracks
directly and isolate motor power if they are moving. At the later resumption,
the operator confirms **REDCON 4, tracks stopped and motor power off**. This
establishes the current physical condition; it does not establish when the
tracks stopped or whether the requested drive/disarm sequence completed.

Evidence: `04-control-{start,shadow-samples}.json*`, `04-control.log`,
`04-interrupted-result.json` and `live-evidence-sha256.json`. The finite recorder
has 64 samples and its final entry includes the native terminal reason.

## Later diagnosis and disarmed resumption

The later operator-selected #171 investigation is recorded in
[the Wi-Fi outage report](tbot-wifi-outage.md). The operator applied a 25 MHz
SDIO-clock trial and later confirmed shared-battery power loss. #171 was closed
at the operator's request for battery hardware follow-up outside this
repository. Neither its closure nor the finite clock trial proves the cause of
the earlier #167 interruptions or establishes a kernel fix.

The resumed #167 read-only preflight still projects actual REDCON 4 with no
board/MAVLink/video capability. Its cached disarmed/Hold MAVLink fields are not
treated as live state. Before a new native run, verify battery readiness,
operator recovery to actual REDCON 1, fresh disarmed/unowned board state and
QGC connectivity. The operator subsequently confirms battery readiness and
live Office/QGC connectivity. Fresh actual REDCON 1 and disarmed/unowned board
state are verified before the next native run.

## Client disconnect/reconnect — verified while disarmed

`05-client-disconnect.log` uses the unchanged native executable. The board grants
actor `QGroundControl`, session `mavlink-2`, epoch 1. The operator disconnects
QGC's `TBot Agent` UDP link and leaves it disconnected. Native authority clears
with `control=0 client inactivity or lease expiry`. Fresh MAVLink version 1048
reports no owner, `armed=false`, Hold, and both connected peers as observers.
Telemetry and video continue. The exact client cutoff timestamp is not measured,
so this capture establishes release without precise deadline measurement.

The operator reconnects QGC. Across a recorded twenty-second window, valid UDP
datagrams increase 1,825 → 1,893, telemetry 7,538 → 8,806 and video 3,290 → 3,846.
Control remains false with no further grant, and the board remains disarmed/Hold
with no owner. Ctrl-C then stops the native run on `process signal` (terminal
group exit 130). Its last reported totals are 10,396 telemetry and 4,540 video;
the finite shadow recorder ends with 36 samples.

Evidence: `05-client-disconnect-{start,result}.json`, native log, raw
`05-client-disconnect-shadow-samples.jsonl`, `05-reconnect-observation.json` and
operator action notes. This disarmed run does not establish physical behavior
on an armed disconnect or release of a held lease during process interruption.

QGC's mode indicator and selection behavior are verified against its exact
[v5.1.5 source](https://github.com/mavlink/qgroundcontrol/blob/v5.1.5/src/Toolbar/FlightModeIndicator.qml).

## Complete manual flow and process release — verified

A new explicit `06-manual-flow.log` session acquires `mavlink-3`, epoch 2.
The operator reports fresh parameters loaded, Manual selected and ordinary Arm
successful, with centered sticks. Fresh MAVLink version 1053 confirms
armed/Manual under the same lease. The operator then briefly nudges the left
virtual stick upward, releases it and confirms **tracks moved, stopped on
release, and QGC showed Disarmed**. Version 1054 confirms disarmed/Manual.

Without restarting or relinquishing the lease, the operator arms again with
centered sticks; version 1055 confirms armed/Manual. Ordinary final Disarm is
confirmed by the operator with tracks physically stopped, and by version 1056.
The sampled arm sequence is false → true → false → true → false, always under
the same QGC/session/epoch. The native log has exactly one grant and retains
control until intentional process interruption.

Ctrl-C then stops the held, disarmed session. The log records `process signal`
and control revocation, and the terminal group exits 130. Fresh post-stop
MAVLink version 1059 reports no owner, disarmed/Hold and only the Office
observer. This is real release of a held lease on process interruption, rather
than inferring release from process exit alone. Last reported counts are
17,128 telemetry, 6,696 video, 8,699 valid QGC datagrams and zero consumer video
drops, rejected UDP datagrams or dropped sends. The 51-sample recorder ends.

Evidence: `06-manual-flow-{start,result}.json`, native log,
`06-manual-flow-shadow-samples.jsonl`, operator action notes and the separate
`06-post-stop` raw shadows. The missing-parameter warning and EKF messages are
not treated as resolved by the successful manual flow.

## Office-first contention — verified

With the native agent stopped, the operator takes Office control without drive
input and confirms the tracks remain stopped. Fresh board state shows Office
as owner under `mavlink-1`, epoch 3, armed/Manual. A new explicit native
`07-office-contention.log` run reports `control=0 control_busy`; Office retains
its lease. No native grant occurs.

The operator releases Office control and confirms stopped tracks. Fresh version
1065 reports disarmed/Hold, no owner and two observers. Across twenty seconds
after release, QGC datagrams increase 2,123 → 2,688, telemetry 4,383 → 5,651 and
video 1,922 → 2,479. The native event history remains only `control_busy`: it
does not acquire when the lease becomes free. Ctrl-C ends the native run; its
42-sample recorder is terminal.

Evidence: `07-office-contention-{start,result}.json`, native log, raw sample
stream, operator action notes and `07-after-office-release.json`.

## Deliberate Office takeover — verified after refreshing Office

`08-lease-loss.log` explicitly acquires QGC/session `mavlink-5`, epoch 4, while
disarmed/Hold. Office initially shows a tooltip without QGroundControl and a
button click has no observed takeover effect. The board retains the QGC lease.
Reloading Office refreshes its tooltip to **Take over MAVLink control from
QGroundControl**; the operator then explicitly takes over with neutral inputs
and confirms physically stopped tracks. Version 1073 reports Office owner
`mavlink-6`, epoch 5, armed/Manual. The native log records `control=0 stale_epoch`
and both media streams continue.

After the operator releases Office, version 1075 reports no owner,
disarmed/Hold and both peers as observers. Across twenty seconds, QGC datagrams
increase 11,446 → 12,012, telemetry 25,689 → 26,958 and video 11,207 → 11,765;
native authority stays false and no new grant occurs. Ctrl-C ends the run, and
its 98-sample recorder is terminal.

The Office owner display is an unresolved UI limitation. Source inspection
shows the observer gets control state on initial connection, and the button's
takeover flag depends on its local state. That is consistent with the observed
reload behavior, but no deployed Office revision or browser trace is captured
to establish the exact cause. No Office fix is made within this native
acceptance task.

Evidence: `08-lease-loss-{start,result}.json`, native log, raw sample stream,
operator action notes and `08-after-office-release.json`.

## Requested REDCON 2 and actual REDCON 4

`09-redcon.log` explicitly acquires QGC/session `mavlink-7`, epoch 6, while
disarmed/Hold at actual REDCON 1. The operator requests REDCON 2. Sparkplug
version 1681 records target 2, command `dcmd-tbot-8yzfgj-25` succeeded, but actual
REDCON stays 1 with board/MAVLink/video capabilities true. The operator confirms
the same displayed result. Both native media counters continue; no selective
video shutdown is observed. A successful target-2 command is not counted as
actual REDCON 2 or as a passed 1→2 transition.

The operator then selects REDCON 4. The native log stops automatically with
`device inactive or dead` and revokes control for that reason; terminal exit is
0. At 17:04:06 UTC the sampler records actual DDATA/4 and unavailable
board/MAVLink/video capabilities. The operator confirms actual 4, board/motor
power off and physically stopped tracks. Last native totals are 18,691
telemetry, 8,142 video and 8,339 valid QGC datagrams, with zero reported queue
drops/rejected UDP/dropped sends. The 63-sample recorder ends.

The separate post-4 read still retains old MAVLink version 1078 with the QGC
owner. This stale field is not fresh evidence of board lease release after
power removal. Actual power-off and native authority revocation are recorded;
fresh board-side lease-state publication is unavailable while the board is off.

Evidence: `09-redcon-{start,result}.json`, native log, raw sample stream,
operator action notes and `09-post-redcon4` raw shadows. The operator is asked
to recover to actual 1, still secured/lifted/disarmed, before a separate device
death check.

## Whole-device power loss and DDEATH — recorded

The operator restores the TBot to actual REDCON 1 and confirms secured/lifted,
disarmed conditions. `10-device-death.log` acquires QGC/session `mavlink-2`,
epoch 1 on the new boot; fresh version 1085 confirms disarmed state. The
operator switches off the entire TBot, including MCU and Pi, while leaving the
rig online, and confirms physically stopped tracks.

Native authority clears on `control request timed out`. The read-only capture
then records actual Sparkplug **DDEATH**, version 1692, at 17:11:30 UTC. The
native process stops with `device inactive or dead`, exit 0. Its last sampled
totals are 3,117 telemetry, 1,501 video and 2,118 valid QGC datagrams, with zero
reported queue drops/rejected datagrams/dropped sends. The MAVLink domain
shadow after power loss is not used to infer fresh board lease expiry/disarm.

The bounded shadow recorder deliberately continues after the native terminal
message to retain later lifecycle/death evidence. It is then interrupted after
32 samples / 151.212 seconds. No owned native process or recorder remains.
Evidence: `10-device-death-{start,result}.json`, native log, raw sample stream
and operator action notes.

The operator identifies a CSI camera and cannot access its ribbon connector.
No cable is disconnected, no camera configuration is changed, and the proposed
camera-absent startup check is not performed. Live video-only failure and actual
REDCON 2 remain open. Camera cable handling requires complete power removal,
per the [Raspberry Pi camera guide](https://www.raspberrypi.com/documentation/accessories/camera.html#connect-the-camera).

## Real verification loss — interrupted earlier by malformed control data

`tmp/issue-167/run-verification-expiry.py` is a local bounded test harness for
the unchanged native executable. The operator creates a 900-second STS session
in a private ignored file. The harness passes that session only in the native
child's environment, disables profile/metadata fallback, records expiry without
secrets, and ends by expiry plus ninety seconds (at most twenty minutes).
The independent read-only recorder retains the normal profile, so it can
distinguish native verification failure from an actual device outage and observe
fresh board lease state after native shutdown. The board stays disarmed.

The intended condition is real expired-session rejection by the cloud API while
existing physical media/control connections remain available. STS's
[documented minimum duration](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetSessionToken.html)
is fifteen minutes. The operator creates the private session file and confirms
live streams, disarmed state and QGC connectivity. Fresh preflight reports
actual 1, disarmed/unowned; file mode is 600 and the native executable hash
still matches. Run 11 starts at approximately 17:22 UTC with credentials expiring
at **17:37:09 UTC / 18:37:09 CET**. The hard harness bound is expiry plus ninety
seconds. Both streams advance and the new QGC lease is held while disarmed.
The independent recorder retains the normal profile.

At **17:37:00.406 UTC**, before the stated expiry, the native log revokes
authority with `invalid control JSON`. The malformed payload is not retained,
so its length, content and cause cannot be recovered from this run. At
**17:37:11.553 UTC**, actual shadow reads fail with `ForbiddenException HTTP
403`. Streams continue to advance, and at **17:37:24.478 UTC** the native process
stops on `lifecycle unverified for 15 seconds`, exit 1. The harness reports no
operator interruption or deadline enforcement. This records real verification
loss/shutdown, but **does not verify release of a held lease on verification
loss**, because control was already revoked for the earlier protocol error.
The exact last successful native API-read timestamp is not logged; the observed
first-error-to-stop interval is about 12.925 seconds, with two-second polling.

Fresh post-stop version 1095 reports no owner, disarmed/Hold and one Office
observer, while actual REDCON remains 1. The native run ends after 873.576
seconds and the 276-sample recorder after 874.390 seconds. Last native counts
are 54,830 telemetry, 25,974 video and 24,433 QGC datagrams, with one consumer
video drop and zero rejected/dropped UDP sends. A separate quarter-second
local log observer retains the failure/terminal observation timestamps.

No session is issued by the agent and no IAM policy changes. The private expired
credential fixture is removed after checking that its credential values occur
in neither native log. Expiry metadata remains in the secret-free audit.
Evidence: `11-verification-expiry-{start,result,exit}.json`, native log, raw
sample stream, `11-verification-boundary.jsonl` and `11-post-stop` raw shadows.

## Native failure diagnostics and bounded reproduction

After run 11, a scoped native diagnostic change adds bounded byte count,
embedded-NUL/object-framing flags and the pending operation to invalid-control
errors. Peer content and parser excerpts are excluded. A regression exercises
empty, truncated, non-JSON and embedded-NUL messages during renewal: authority
releases, queued sends are fenced, observation continues, later traffic does
not reacquire, and private payload text is absent from diagnostics.
`just agent::test` passes 3/3 CTest targets and 19 Python checks.

The updated executable SHA-256 is
`8b384c9559027fa80930323bc07a64b5aa1f523dfe6b3c408ec18d5ca053f336`.
Earlier runs through 11 use the original `baf1ed87…` executable. Both source
files and the uncommitted patch are hashed with the run-12 identity.

`12-protocol-diagnostic.log` then explicitly acquires QGC/session `mavlink-3`,
epoch 2, with normal credentials and remains disarmed/Hold for a bounded
fifteen-minute reproduction attempt. No malformed-control event recurs. At
900 seconds the harness deliberately sends SIGTERM; native authority clears
on `process signal`, the terminal group exits 143, and the harness joins it.
Fresh post-stop version 1099 reports no owner, disarmed/Hold and one observer.
The last counts are 55,530 telemetry, 26,848 video and 25,235 valid QGC
datagrams, with ten consumer queue drops and zero rejected/dropped sends.
Its 285-sample recorder ends. This finite non-recurrence does not resolve the
original malformed-message cause. Evidence: `12-protocol-diagnostic-*` and
`12-post-stop` under the evidence directory.

## SDK/board send race — repair source prepared, rollout pending

Source inspection finds the pinned SDK's `sctpSessionWriteMessage` mutates
session-shared `spa` send metadata, including the text/binary PPID. The board
worker sends binary telemetry on its gRPC reader thread and text replies on
its data-channel callback without a shared send lock. Native `Peer::send`
already serializes its outbound calls. Current upstream retains the same
[shared send metadata](https://github.com/awslabs/amazon-kinesis-video-streams-webrtc-sdk-c/blob/master/src/source/Sctp/Sctp.c).

A deterministic source-extracted unit test compiles the exact pinned function
with minimal layout/sendv shims and controls two overlapping sends. Both
interleavings fail: text can be labelled binary, and binary can be labelled
text. A candidate per-call `spa` object passes both. The candidate patch passes
`git apply --check` against the pinned SDK source. This establishes the isolated
metadata-overwrite defect; **it is not real-SCTP/physical acceptance or proof
that it caused run 11**. Complete SDK API serialization, diagnostic counters
and callback/teardown lock ordering also need review before choosing a remedy.

The SDK candidate is not applied to dependency builds. The chosen production
repair serializes complete board-side SDK calls, following native `Peer::send`.
`SerializedDataChannel` is owned per peer; both the gRPC telemetry reader and
the SDK control-response callback use it. Closing waits for an in-flight send,
blocks later binding/writes, and releases its lock before joining the reader
and freeing the SDK peer. A replacement channel rejects old callbacks. No SDK
pin, message envelope, authority, lease, epoch, lifecycle or IPC contract changes.

Mixed-producer and close/rebind regressions pass in the board test suite. The
actual board sender is also used in a local real-SDK stress fixture: 1,000 binary
frames and 1,000 text control replies are delivered with their type/content
preserved, with replies sent from the SDK receive callback while a separate
thread sends telemetry. All 3 agent CTest targets and 19 Python checks pass.
The board suite passes both its stub and real-SDK Mac builds; the real SDK
backend compiles and reports version 0.18.3. The agent source-package allowlist
includes the shared test header so its existing container test build remains
complete. These automated/local builds do not replace the pending physical
repetition on the updated board.
The rebuilt native agent hash after SDK stress-test integration is
`df306c4f671a9dab56848ae50dde8ff249b0dab4d28e404da7350582d1e45f0b`;
run 12 retains its distinct `8b384c95…` executable identity.

`release/versions/kvs-master` is prepared at 0.18.3; neither its immutable release
nor tag existed when checked. The deployed board remains 0.18.2. After the
operator starts Lima, the repository's pinned Alpine 3.24.1 ARM64 build passes,
including the production SDK/gRPC backend and board CTest suite. The resulting
ELF requests `/lib/ld-musl-aarch64.so.1`, resolves the expected libcamera 0.7
libraries, and reports version 0.18.3. All pre-build source hashes match.
Its SHA-256 is
`c2ec5c0143b74eb7e9bcaf38c291d808d040b16cd9dbc0a6b2608d34fd9a9c44`.
A separate fresh Alpine runtime container also passes the repository's
musl/libcamera version smoke check, without using the build container.
The earlier Lima boot-session/SSH failure is retained as historical evidence.
Explicit commit/push, operator-dispatched immutable release, coordinated manual
TBot maintenance and affected physical repetition remain required. No production
installation or publication is performed automatically.

Review: `protocol-race-review.md`, the source changes, `sctp-send-candidate.patch`,
`check-sctp-send-interleave.py`, generated C++ cases, `sctp-interleave-result.json`
and the board/agent test logs in the evidence directory.

The operator parks the TBot at actual REDCON 4 and confirms board/motor power
off and physically stopped tracks. All owned native processes and recorders
through run 12 are terminal. No camera cable was disconnected, no board repair
deployed and no commit created. #167 remains open.

## Resumption on KVS 0.18.3 — 2026-10-26

The operator reports installed `txing-board-kvs-master 0.18.3` and REDCON 1.
Their `/boot/usercfg.txt` output retains `camera_auto_detect=1`, the PWM overlay
and the existing `dtparam=sdio_overclock=25` trial. This is operator-supplied
configuration evidence, not a verified repair of the earlier power/kernel fault.

At resumption, the working tree was clean at
`dd252da7c37bcebbfdec1463e67e0ef39ef196fd`,
committed outside this agent's actions. All eleven source hashes match the
prepared repair. The published `kvs-master-v0.18.3` release targets that commit.
Its downloaded archive matches GitHub's SHA-256 digest
`ae9e1692c2291cd10cea6c990705580db827204c4ef5ec5d31d78183604a889d`;
the sole root-level stripped binary has SHA-256
`562f1c89d015564fa95f333f0cfa51964825219c21f4c37328d3003577d396d1`.
This differs from the earlier unstripped local build and does not by itself
establish which executable the board service is running. The operator then
reports OpenRC status started and confirms both the installed binary and
`/proc/2655/exe` match the release binary checksum above.

A new read-only preflight captures Sparkplug version 1717, actual DDATA/REDCON 1
with board/MAVLink/video available. MAVLink version 1109 reports a ready link,
fresh heartbeat, disarmed Manual and one observer. Command 32 was recorded at
09:15:21 UTC; the current-stage fifty-minute ceiling still applies across
replacement native runs. The operator reconfirms secured/lifted conditions,
tracks clear, disarmed/stopped, Office View only and QGC connected with centered
sticks. A new bounded native run starts at 09:23 UTC with the same `df306c4f…`
executable and a read-only shadow recorder. Initial telemetry negotiation times
out awaiting an SDP answer, then retries successfully while video stays live.
Both streams advance, but QGC UDP remains zero and no control grant occurs.
The operator is asked to reconnect the configured QGC link; no arm or drive
instruction is given during that interval. After the operator confirms the
reconnection, QGC traffic arrives and native control is acquired. Fresh MAVLink
version 1111 confirms QGroundControl/session mavlink-2/epoch 1, disarmed Manual.
The operator is then instructed to refresh parameters, select Manual and use
ordinary Arm with force-arm off and sticks centered; driving is not yet
requested. Raw preflight, release identity and live run evidence are retained
under `tmp/issue-167/13-*`.

Fresh parameter retrieval and ordinary Arm/Manual are confirmed by the operator
and shadow version 1112. Before any drive, QGC reports Comms Lost and a failed
Arm/Disarm response. The operator clarifies that no drive was performed. Native
authority clears on `control request timed out`; telemetry freezes at 15,940
while video continues. Fresh version 1114 reports no owner, disarmed/Hold
(field metadata timestamp 09:29:09 UTC). This is fresh board state after the
loss, not confirmation that the operator's Disarm command succeeded. Neither
physical movement/stop-on-release nor re-arm is accepted.

The fifteen-second telemetry-silence watchdog retires only MAVLink; the stream
reconnects and its counters resume by the 09:29:34 sample while video keeps
advancing. QGC traffic continues with no automatic control reacquisition. One
grant and one timeout revocation are recorded, with no malformed-JSON event.
The cause remains unconfirmed; neither the 0.18.3 repair nor the SDIO trial is
declared to resolve this failure.

The run is deliberately stopped at 09:31:01 UTC after 444.410 seconds, native
process-group exit 143. Last counts are 21,384 telemetry messages, 12,019 video
frames and 9,729 valid QGC datagrams; one consumer video drop, zero UDP
rejects/drops. The 136-sample main recorder is terminal, as are the bounded
post-failure and parked recorders. The operator confirms actual REDCON 4,
board/motor power off and physically stopped tracks; fresh Sparkplug version
1720 agrees. This failed repeat keeps the manual-flow gate open. Next diagnosis
must remain disarmed and correlate board logs with any repeated timeout.
`13-repaired-manual-flow-result.json` retains the source/installed identities,
transitions, operator reports, run result and exact evidence limits.

## Disarmed diagnostic capture — 2026-10-26

The operator recovers to REDCON 1 with QGC disconnected and supplies fresh
startup log lines: two `onSetStunServerIp` errors and one
`onSctpSessionDataChannelOpen` error, each status 0x00000001, followed by a
MAVLink data-channel-open marker. They report that the old failure log is lost
on the read-only-root device. No remount or log-persistence configuration is
changed. Instead, the operator confirms a filtered SSH log stream saved on the
Mac as `tmp/issue-167/14-board-kvs-live.log`, keeping new evidence across a later
board power-off. The old run-13 board log remains unavailable.

The pinned SDK defines this code as `STATUS_NULL_ARG`. The early-STUN function
can emit it when its optional shared context is uninitialized; the incoming
data-channel function checks both the peer pointer and registered callback.
A video peer with MCP disabled deliberately lacks that callback. The supplied
line has no peer identity, so this is a possible interpretation rather than an
assignment to a particular peer or the cause of run 13. Actual MAVLink attachment
and fresh telemetry are independently observed after the startup errors.

Preflight versions 1725/1122 show actual 1, available streams, disarmed Manual
and one observer. Command 34 dates to 09:39:20 UTC, giving the activation's
current-stage ceiling of 10:29:20 UTC. Run 14 starts at 09:48 UTC with the
unchanged `df306c4f…` native executable, a 900-second bound and a read-only
shadow recorder. QGC is initially disconnected: both observers stay disarmed,
no control grant occurs and UDP counts stay zero. Telemetry attaches directly;
video retries after an initial unanswered offer, then advances independently.
The operator is instructed to reconnect QGC and refresh parameters while
keeping sticks centered, the Mac capture running and the TBot disarmed.

The operator confirms fresh parameters and Disarmed. One lease grant is
recorded under mavlink-2/epoch 1. The same control timeout then recurs entirely
disarmed: fresh version 1126 is unowned/disarmed/Hold, MAVLink silence triggers
retirement and reconnection, and video continues. Later QGC traffic does not
reacquire control. All 146 captured samples are disarmed. The filtered board
capture has no corresponding MAVLink bridge error; a frozen run snapshot is
retained separately from the still-running SSH stream. Its startup signalling
send timeout (0x0000000f) precedes acquisition and cannot identify the later
control-timeout cause. The stream contains a new peer-open marker on recovery.

Run 14 is deliberately stopped after 494.510 seconds, group exit 143. Final
counts: 25,605 telemetry, 13,725 video, 9,114 QGC datagrams; 21 consumer video
drops, zero UDP rejects/drops. The main and post-stop recorders are terminal.
Fresh post-stop state remains unowned/disarmed/Hold at actual REDCON 1. The
operator-run SSH log capture stays open; no drive or arm is attempted. Evidence:
`14-disarmed-diagnostic-result.json` and `14-board-kvs-run-snapshot.log`.

The operator cannot run sudo on the Mac; the proposed packet capture is not
performed. A native-only diagnostic change adds periodic and teardown SDK ICE
packet/byte/consent counters and adapter counts of SDK send results and receive
callbacks, with numeric status and sample time. The first real-SDK regression
finds that the pinned SDK remaps a locally created channel's private ID without
updating its public ID, making its data-channel metrics lookup fail. The
production diagnostic uses adapter callback/API counts instead of a private-ID
workaround; this lookup finding is not the cause of the actual control failure.

The final real-SDK regression verifies live bidirectional ICE and 1,000 sent /
2,000 received data-channel messages, and checks that diagnostic fields have
numeric values without labels or payload. All 3 CTest targets and 19 Python
checks pass. Existing worker/lifetime locks are used; no new queue/thread,
addresses, credentials or peer content are introduced in the diagnostic.
Authority, lifecycle and recovery remain unchanged. Native executable SHA-256 is
`907c318866be09ee852f28ac1818fcff1ff1be18cd5a1d8b54ea1e94bdd9d912`.
Run 15 starts with that uncommitted diagnostic source and a ten-minute bound,
within command 34's activation ceiling. Fresh parameters load; the operator
reports Not Ready / Hold and leaves the TBot disarmed. It holds one lease under
mavlink-4/epoch 2 for the rest of the observation without reproducing a control
timeout or later telemetry retirement. The initial MAVLink offer needs a retry;
the filtered board log captures startup signalling/TURN errors, followed by a
successful peer open. They are not assigned as the cause of runs 13/14.

The harness ends run 15 at its 600-second deadline (600.256 seconds elapsed,
group exit 143). Native process-signal revocation is followed by fresh version
1133, unowned/disarmed/Hold. The 185-sample recorder and post-stop sampler are
terminal. Last pre-stop totals: 36,165 telemetry / 16,464 video / 11,849 valid
QGC datagrams, 369 consumer video drops and zero UDP rejects/drops. The drop
count belongs to the bounded consumer queue, not observed network packet loss.
All captured samples remain disarmed.

There are 235 SDK counter snapshots, including periodic and teardown samples.
Connected periodic telemetry/video samples number 114/118; maximum sampled
last-packet ages are 358/27 ms, with zero API-send failures. These five-second
samples and callback/API counts are not a packet capture or proof of continuous
wire delivery. This finite non-recurrence does not identify or fix the earlier
timeouts and supplies no motion acceptance. The operator stops the SSH capture,
disconnects QGC and confirms actual REDCON 4, board/motor power off and tracks
stopped. Logs and a frozen board snapshot are retained on the Mac. A fresh
activation with the same diagnostics is prepared for another manual-flow
repeat; it has not started yet.
No board root/configuration change or new board release is needed for this
native diagnostic. No passing motion test is claimed.

## Manual-flow repeat with counters — 2026-10-26

After the parked checkpoint, the operator starts a fresh REDCON 1 activation and
reconfirms live Office video/MAVLink, secured/lifted conditions, clear tracks,
disarmed/stopped, Office View only and QGC disconnected. A new filtered SSH
capture is saved to `16-board-kvs-live.log` on the Mac. Run 16 uses the same
`907c3188…` executable, a fifteen-minute bound inside the new activation ceiling,
and a read-only shadow recorder. Both streams attach; fresh MAVLink version
1139 is disarmed Manual with two observers and no owner. After QGC reconnects,
the operator confirms fresh parameters and then completes ordinary Arm, slight
one-second throttle, stop on full release, ordinary Disarm, ordinary re-arm
with centered sticks, and final Disarm with physically stopped tracks. No
force-arm or further movement is used. Shadow versions 1140–1144 capture
false → true → false → true → false in Manual under the same
QGroundControl/session mavlink-2/epoch 1 lease. Native logs contain one grant
and no intervening control loss. The complete manual-flow criterion passes
again on installed KVS 0.18.3 and the current native diagnostic build.

The native session is deliberately stopped at 10:39:19 UTC after 588.204
seconds, group exit 143. Last pre-stop counts: 34,345 telemetry messages, 16,141
video frames, 12,899 QGC datagrams; 255 consumer video drops, zero UDP
rejects/drops. Signal revocation is followed by fresh version 1146,
unowned/disarmed/Hold. The 183-sample recorder and post-stop sampler end; a
frozen board log snapshot is retained. Earlier timeout causes remain unresolved.

## Verification-expiry repeat — 2026-10-26

The operator keeps the TBot disarmed, disconnects QGC, retains Office View only
and the Mac board-log capture, then manually creates a private 900-second STS
session. Run 17 checks ownership/mode 0600 without logging the credential tuple;
only the child receives it, with profile/metadata fallback disabled and empty
repository-local AWS configuration. The actual expiry is 10:58:41 UTC. The
native run starts with the same `907c3188…` executable, has an expiry-plus-90-second
bound within the activation ceiling, and uses the normal-profile read-only
sampler for independent board evidence.

The operator misses the QGC reconnect window. All native UDP/control counts stay
zero, and no lease is acquired. Actual shadow reads then fail HTTP 403 at expiry;
the native process ends at 10:58:55.952 UTC with `lifecycle unverified for 15
seconds`, exit 1, without a signal or harness deadline. This is 14.952 seconds
after the recorded credential expiry; the exact last successful native API-read
timestamp is not separately logged. The 240-sample recorder ends. Last totals:
49,031 telemetry, 20,838 video, 189 consumer drops, zero QGC datagrams. Real
verification shutdown is recorded, but release of a held lease remains unproved.

When the operator later reports QGC remaining disconnected, the old native relay
has already ended. Late normal-profile reads show actual 1 and unowned/disarmed/
Hold; they do not establish a held-lease release that never occurred. The private
expired fixture is removed after checking its actual credential values against
fifteen evidence files with zero matches. The operator corrects an initial
Office/power-off problem report and confirms actual REDCON 4, disconnected and
power off; fresh Sparkplug 1738 agrees. All owned native processes and recorders
through run 17 are terminal.

For the next attempt, normal-profile QGC connectivity must be established first.
Only then create a fresh temporary session and hand over to the expiring native
process while leaving the already-configured QGC UDP link connected. This avoids
requiring another timed UI reconnect after issuing credentials.

## Normal baseline and connected expiry handoff — 2026-10-26

The operator recovers a fresh REDCON 1 activation, with secured/lifted conditions,
disarmed/stopped, Office View only and a new Mac SSH capture
(`18-board-kvs-live.log`). Run 18 uses normal `mayor` credentials and the same
`907c3188…` native executable. After the agent receives both streams, QGC's
Comm Links row shows Disconnect and its vehicle is connected. Real UDP traffic
and shadow version 1169 verify QGroundControl/session mavlink-2/epoch 1 while
disarmed. The operator keeps the link connected and manually creates a fresh
private 900-second STS fixture only after this baseline works.

The normal native process is deliberately stopped after 480.440 seconds,
group exit 143; its 147-sample recorder ends. Fresh independent preflight
confirms release and disarmed state before an explicitly started replacement.
The new bounded run 19 uses the temporary tuple in its child environment only,
with empty local AWS configuration and profile/metadata fallback disabled.
The existing QGC UDP link remains connected through this handoff. After an
initial MAVLink offer retry, both streams advance and native control is granted;
fresh version 1174 verifies disarmed/Hold under mavlink-3/epoch 2.

The actual credential expiry is 13:20:52 UTC (15:20:52 Berlin). The independent
recorder retains normal credentials. Run 19 encounters another control timeout
and MAVLink gap before that expiry, while video continues. Its saved SDK counters
show the affected association remaining nominally connected, no reported send
errors and stalled receipt before retirement; they do not identify the underlying
cause. It recovers observation without reacquisition and is deliberately stopped
at 13:16:19 UTC after 576.252 seconds, exit 143. The 179-sample recorder ends.
This invalidates held-lease verification proof for run 19.

A new explicit disarmed run 20 reuses the still-valid tuple close to its original
expiry. Its expiry is unchanged; no system clock, credential lifetime, lifecycle
response or timeout is simulated or modified. With about 149 seconds remaining
at startup, both streams attach after one MAVLink offer retry; fresh version 1180
confirms QGroundControl/session mavlink-5/epoch 3, disarmed/Hold. The QGC UDP link
remains connected. A separate pre-expiry snapshot and the native log confirm
authority remains held until real verification loss, with no earlier revocation.

The boundary observer detects actual shadow-read HTTP 403 at 13:20:53.968 UTC,
then `agent stopped: lifecycle unverified for 15 seconds` at 13:21:06.872 UTC.
Native authority clears for that same lifecycle reason and the process finishes
at 13:21:09.117 UTC, exit 1, without a signal or harness cutoff. Observer times
are file-poll detection times; the exact last successful native API-read time
is not logged. Fresh normal-profile version 1182 is unowned/disarmed/Hold with
only the Office observer. **Held-lease release on real verification loss passes.**
The 52-sample recorder and boundary observer are terminal. The expired fixture
is removed after zero credential-value matches across 31 evidence files.

Both cases retain raw logs, SDK samples, actions and independent shadows; the
combined board snapshot is `19-20-board-kvs-snapshot.log`. Earlier transport
timeout causes remain unresolved. The next camera-only test is prepared for the
operator-identified IMX708/Unicam platform device `3f801000.csi`, with explicit
bind/restart recovery and fresh activation required before the fault. No camera
detach has been performed yet.

## Camera-only loss and stale readiness — 2026-10-26

After a fresh operator 4→1 cycle, run 21 establishes real video and MAVLink,
QGC connected/disarmed, and one QGroundControl/mavlink-2/epoch 1 lease. The
operator detaches only the verified Unicam receiver `3f801000.csi` through its
sysfs `unbind` entry; exit status is 0. No ribbon cable is disconnected, root
remount is needed, or arming/motion input is sent.

Encoded video stops at **6,669 frames**. Board logs show the camera frontend
timeout and `/dev/video0`/`video1` removal. Sparkplug version 1753 reaches actual
REDCON 2 with board/MAVLink capabilities available and video unavailable. The
native operator closes only video; telemetry and the same disarmed control
lease continue. However, version 1754 returns to actual 1 after a viewer-count
READY callback, and the reopened video peer receives no further frames. Office
reports actual 1 and “connecting to board video…”. This is a failed readiness
case, not final acceptance of selective video loss or REDCON 2 behavior.

The runtime catches camera failure and publishes ERROR, but keeps the video
KVS session alive while waiting for the independent MAVLink thread. Its
`ReportReadyViewerCount` callback can then override ERROR. The repair stops the
capturer and video signaling/peers before publishing the final ERROR and
waiting. The process-wide SDK and separate MAVLink loop stay available until
the normal worker stop. No schema, authority, SDK pin or retry policy changes.
The regression supplies a first keyframe, a camera error, a late viewer-count
callback and an explicit shutdown with the control thread configured. It fails
on 0.18.3 and passes after the cleanup-order fix.

Validation passes the stub regression, canonical native board suite, real-SDK
macOS suite, and production Alpine ARM64 real-SDK/gRPC suite. The fresh Alpine
runtime smoke passes with version 0.18.4 and resolved libcamera 0.7 libraries.
The local unstripped artifact SHA-256 is
`6befe6df22b1947d89e71f5dad1762d595bf961a6ba35bc5427dfc54daee09f1`.
Its source inputs match the recorded pre-build hashes. This artifact has not
been published or installed; the later immutable release rebuild has its own
asset/install identity.

The native session is deliberately stopped after **737.025 seconds**, group
exit 143. Last counts: **41,562 telemetry / 6,669 video / 12,029 valid QGC
datagrams**, 52 bounded consumer video drops and zero UDP rejects/drops. All
196 shadow samples remain disarmed; fresh version 1196 is unowned/disarmed/Hold
after shutdown. Operator stop/bind/start commands succeed but camera recovery
does not: actual 2/no video remains, and libcamera cannot reopen the sensor
node. The operator stops the capture and confirms actual 4, board/motor power
off and tracks stopped. A new power cycle is required before the physical
repeat; sysfs rebind is not recorded as a successful recovery.

Raw `21-*` logs, triple-shadow samples, frozen board log, operator actions and
result JSON are retained under `tmp/issue-167/`. Repair plan and validation
are under `22-*`. The prepared KVS version is 0.18.4. Publish its immutable
release only after an explicit operator commit/push, then use the coordinated
[TBot maintenance procedure](components/board.md#maintenance). Repeat the
camera-only fault while disarmed and verify stable actual 2, no video reconnect
or new frames, continuing MAVLink and fresh parameter retrieval. Keep #167 open
until real evidence supports those results.

## Installed 0.18.4 repeat and camera cleanup ordering — 2026-10-26

The operator independently commits the previous repair and native diagnostics
at `219f3c871eb8a6fc649a80180eb51c8da730d53a`, publishes `kvs-master-v0.18.4`,
and installs it. The worktree is initially clean. The downloaded immutable
archive SHA-256 is
`cc3749b081051856492687b92b2d28041aca0efbdef3d97d9ec107917771380c`;
its executable SHA-256
`39facd7cb51a7836fba526797b4798ab1e761276c14bed3e6e313c6bbd7417c9`
matches both the operator's installed executable and running PID 2656.
These are distinct from the earlier local unstripped artifact. The same native
executable `907c3188…` and its source hashes are reverified. No agent commit,
publication or installation is performed.

In run 23, fresh actual 1/video/MAVLink and disarmed/unowned state are verified
before starting the bounded native session. The operator confirms the lifted
setup, Office View only, centered sticks and Mac log capture. After connecting
QGC and freshly loading parameters, one QGC/mavlink-2/epoch 1 lease is granted.
The operator's exact Unicam detach returns 0. Frames freeze at **3,272**, while
telemetry and the same disarmed lease continue. Actual REDCON remains 1, and
Office refresh still shows “Connecting to board video…”. All 77 shadow samples
remain disarmed. This is another failed physical readiness case.

Camera teardown logs reach removed-device/buffer cleanup. The main worker's
kernel wait channel/stack show a futex wait; the exact userspace function is
unidentified. The attempted per-thread listing fails and supplies no further
evidence. Source ordering explains why this can hide video failure: 0.18.4
calls capturer `Stop` before closing video and reporting ERROR. A camera
cleanup wait delays both. The earlier regression incorrectly required camera
cleanup completion before the error report.

The 0.18.5 correction closes/drains the video session, reports ERROR, then
releases camera resources. This preserves the READY-callback protection while
removing camera teardown from the readiness-publication path. The separate
MAVLink loop continues. The revised regression verifies video closure and
ERROR are already visible at camera-stop entry; it fails on 0.18.4 (three
assertions) and passes with the correction. Secret-free failure-stage markers
identify video closure, camera-release entry and completion if another wait
occurs. No new thread, schema, authority, SDK pin or retry policy is added.

The corrected stub regression, canonical native suite, real-SDK macOS suite,
production Alpine ARM64 real-SDK/gRPC tests and fresh-runtime smoke all pass.
Source hashes match the recorded build inputs. The local unstripped 0.18.5
artifact SHA-256 is
`e29900247af1cd018ad382610bc34f01a702a4414c4c0c7955a5a22a01816b9a`;
musl/AArch64 and libcamera 0.7 linkage are verified. This is build evidence;
0.18.5 has not been published, installed or physically accepted.

The native process is deliberately stopped after **308.823 seconds**, group
exit 143. Last observation: **16,397 telemetry / 3,272 video / 5,542 valid QGC
datagrams**, 71 consumer video drops and zero UDP rejects/drops. Native control
clears for the process signal; fresh version 1220 is unowned/disarmed/Hold.
The operator stops the capture, disconnects QGC and confirms actual 4,
board/motor power off and tracks stopped; fresh Sparkplug 1776 agrees. No
software camera recovery or additional motion is attempted.

Evidence is frozen under `tmp/issue-167/23-*`; the correction plan, validation
and manual rollout instructions are under `24-*`. The installed board remains
0.18.4. The 0.18.5 source/artifact requires an explicit operator release and
coordinated maintenance before another real camera-loss test. Earlier
unrelated control-timeout causes remain unresolved. Criteria 4 and 6 stay open.

## Real video isolation and entry at REDCON 2 — 2026-10-27

The operator independently commits the cleanup-order correction at
`613e335b99162209cac646d3c60b1a44561b22fa`, publishes `kvs-master-v0.18.5` and
installs it. The downloaded archive SHA-256 is
`6ad54d784567564d87e4e619c77fc18efe3e6a34267185490f96da2ec5541c43`;
its executable SHA-256
`6e886995f48429d123289b00e07642920ba2e240e23af3ae4e0c63ed496f8ae3`
matches both installed bytes and running PID 2654. Source starts clean. The
same native executable `907c3188…` and its source hashes are reverified. No
assistant commit, release or board installation occurs.

Case 25 establishes both real streams at actual 1, fresh QGC parameters and one
disarmed QGC/mavlink-2/epoch 1 lease. The operator's Unicam detach returns 0.
Video freezes at **1,933 frames**; the worker reports `closing_video`, then
`releasing_camera`. The video shadow reports ERROR/not ready and the projection
reaches actual 2 with `capability.video=false`. It remains at 2 for **143.794
observed seconds** through the end of this run. Fresh QGC parameter names and
values load while Disarmed; telemetry and the same lease continue. A failed
video recovery attempt occurs during loss/lifecycle propagation before final
closure; raw connection order is retained and per-event timing is not separately
logged. No new video frames or later readiness revival occurs.

Camera-release completion is not observed: `camera_released` is absent. The
diagnostic stage narrows the remaining cleanup wait but does not identify the
exact library call. That wait no longer hides video failure or stops MAVLink.
This passes real video-only isolation and the live 1→2 behavior. The native
session ends deliberately after **237.862 seconds**, group exit 143. Last
observations: **13,595 telemetry / 1,933 video / 4,816 QGC datagrams**, 62 bounded
consumer video drops and zero UDP rejects/drops. All 63 shadow samples are
disarmed; fresh version 1235 is unowned/disarmed/Hold after release.

Without rebinding or restarting services, a new explicit case 26 starts from
actual 2. It opens only MAVLink, acquires QGC/mavlink-3/epoch 2 and retrieves
fresh parameters while Disarmed. There is **no video peer and zero video
frames**. All 68 samples remain actual 2 and Disarmed. Deliberate stop after
**249.972 seconds**, group exit 143, records **15,512 telemetry / 4,916 QGC
datagrams**, zero UDP rejects/drops and zero video drops. Fresh version 1239 is
unowned/disarmed/Hold. This passes fresh entry at actual 2 with MAVLink alone.

The operator then performs a real 4→1 power cycle and confirms restored live
video/MAVLink, secured/lifted/disarmed/stopped conditions, Office View only and
centered QGC sticks. Fresh actual 1 and ready streams independently confirm
recovery. The operator reports no rights for packet capture; none is performed
or requested again. Frozen case/result/provenance/board logs are under
`tmp/issue-167/25-*` and `26-*`.

## Recovered stability observation and remaining diagnosis — 2026-10-27

Case 27 runs normally at actual 1 after that power cycle. Fresh parameters load
while Disarmed; video/MAVLink continue under one QGC/mavlink-2/epoch 1 lease.
The bounded fifteen-minute observation ends at **900.250 seconds**, group exit
143, on the harness signal, not a spontaneous transport/lifecycle failure.
The 232-sample recorder ends. Last observations: **56,786 telemetry / 24,776
video / 12,215 QGC datagrams**, 307 consumer queue drops, zero UDP rejects/drops.
The only control loss is the final process signal; fresh version 1249 is
unowned/disarmed/Hold. This is finite non-recurrence, not proof of the cause or
repair of the earlier intermittent control/telemetry stalls.

A standalone local SDK probe attempts a forced overlap between the shared
writer and a receive-callback reply. Its local peers fail to connect, so the
schedule is never exercised. The result is **inconclusive**, not a demonstrated
deadlock. No production concurrency change is made on that basis.

The prepared 0.18.6 diagnostics add numeric operation counts, pending ages and
completion timings on the board, sampled by the existing cleanup worker and at
teardown entry. They distinguish receive callbacks, control bridge dispatch,
uplink writes, telemetry/reply writer waits and SDK sends without acquiring
their operation locks for a counter snapshot. Fixed fields exclude payloads,
credentials and remote identity. Tests cover blocked-call visibility,
concurrent counts, exception accounting and numeric-only bounded output.
Authority, SDK pins, queues, threads, retries and deadlines are unchanged.
This diagnostic build is not a timeout repair or physical acceptance result;
manual release/maintenance/retest is required before its board-side data exists.

The functional video/REDCON checkboxes are now supported by cases 25/26 and
the previously recorded real REDCON 3/4/death cases. The overall gate remains
open for the earlier unresolved transport behavior. No later cloud work starts.

## Required Office takeover — failed attempt and prepared client repair

After case 27 ends and QGC disconnects, the operator tries the Office control
button twice. Exact notifications in Europe/Berlin on 2026-10-27 are
**08:35:02** and **08:35:11**, both `Timed out waiting for control.activate`.
These are activation-exchange timeouts, not Manual/Arm command rejections.
Intermediate grant/expiry states are not captured. Later fresh MAVLink version
1253 is unowned/disarmed/Hold. The operator selects REDCON 4 at **08:37:59** and
confirms actual 4/power off; Sparkplug 1802 independently reports actual 4 and
unavailable board/MAVLink/video capabilities.

The operator explicitly reiterates the design requirement to take manual
control from Office. This attempt remains blocking even though the preceding
video/REDCON checks pass. The current source derives takeover=true/false from
cached owner state; its control-request timeout rejects without retiring the
channel, so repeated clicks can reuse the same unresponsive peer. There is
also no established receive-silence deadline. These are verified recovery and
policy gaps; the exact transport cause of the missing replies is unproved.

Prepared Office **0.18.3** makes the explicit manual action request takeover
independently of cached ownership. The tested high-level client operation
preserves ordinary Manual/Arm preparation, no force-arm override, and safe
release if preparation fails. A control timeout closes the session, and
fifteen seconds without received messages retires an apparently open peer.
The existing backoff replaces the observer connection in View only. No failed
takeover is automatically replayed, and late replies/flight telemetry from a
closed session are ignored.

Two new recovery regressions fail on the old client and pass with the repair.
Additional tests verify the actual takeover envelope with an empty owner cache,
ordinary Manual/Arm frames, preparation rejection/release, no Arm after failed
acquisition, receive-activity deadline extension, and a fresh explicit retry.
All **213 Office tests**, lint and the production build pass. The shared Office
and component version files are aligned at 0.18.3. One existing unused-argument
lint error is cleared without changing cmd_vel behavior.

The source is uncommitted and not deployed. Rollout/retest steps are prepared
in `tmp/issue-167/29-operator-office-takeover.md`: publish Office through its
existing Git/Cloudflare path, load the new client, then verify a real Office
takeover from an active QGC lease without reloading Office, old-agent fencing,
stopped tracks and safe release. The Office action ordinarily arms the vehicle,
so that retest remains an operator-run secured/lifted procedure. Board 0.18.6
diagnostics support further diagnosis but do not claim a transport repair.
Keep the Office handoff criterion and #167 open until the physical path works.

## First foreground run

Use Office to select REDCON 1 and wait for actual 1 with available MAVLink/video.
Configure QGC's link as above; avoid a duplicate UDP auto-connect link on 14550.
Leave Office in View only and begin without `--control`.

From the repository root, run this in a foreground terminal:

```sh
AWS_PROFILE=mayor just agent::run tbot-8yzfgj --region eu-central-1 \
    > tmp/issue-167/01-observation.log 2>&1
```

The terminal stays occupied by the agent while the log is captured. The agent
can follow the file; use Ctrl-C in that terminal to stop the run. Record the
command start/end, actual QGC link settings, displayed vehicle/telemetry and
increasing native telemetry/video counts. The first video observation must
include H.264 bytes, presentation timestamp and receipt timestamp. Observation
must leave board control unowned; no parameter-retrieval success is inferred
from cached QGC values. Record the lack of an `agent` shadow before/after and
the existing local code's read-only IoT API path.

For later control cases, stop the observation run first. Only after the operator
starts the explicit command and `control=1 acquired` is recorded may QGC send
full MAVLink traffic:

```sh
AWS_PROFILE=mayor just agent::run tbot-8yzfgj --control --region eu-central-1 \
    > tmp/issue-167/02-control.log 2>&1
```

These commands use existing IoT/KVS device resources. They do not deploy agent
infrastructure, invoke a controller, or write an agent shadow. Physical inputs,
Office ownership, REDCON/death changes and live fault induction remain manual.
End each native session by fifty minutes under the
[current-stage limit](constraints/agent-session-limit.md); existing board renewal
can interrupt earlier. Record that interruption as a result, without bypassing
the lifecycle rule or repairing the deferred credential-renewal/kernel issue.

## Cases and required observations

Each row remains pending until its actual logs, board state and operator
observations are recorded. Use separate named logs for separate runs. Retain
failed attempts and the source/executable identity for every retry.

| Case | Required physical evidence | Status |
| --- | --- | --- |
| Observation | QGC receives live telemetry; native operator receives/counts encoded video at actual REDCON 1; no control acquisition | Streams/QGC messages verified; full numeric GUI display unverified |
| Parameters and one control session | Fresh parameter retrieval after free-lease grant; operator arms, drives, stops input, disarms, re-arms and finally disarms; native grant remains continuous and board session/epoch unchanged throughout | Passes again in run 16 on KVS 0.18.3/current native diagnostics; failed runs 13/14 and their unresolved cause remain recorded |
| Office contention | Office acquires first; a fresh explicit agent run reports busy, does not displace Office and sends no uplink; after Office releases, the same agent run still does not acquire automatically | Run 07 reports busy, preserves Office ownership and does not acquire after release |
| Client inactivity/disconnect | With control held and motion stopped, disable QGC heartbeat/traffic or disconnect its UDP link; board/native authority clears at the five-second client deadline; reconnecting never reacquires | Disarmed disconnect releases board/native authority; reconnect does not reacquire; exact cutoff timing unmeasured |
| Process interruption | Ctrl-C/SIGTERM on the foreground agent releases its real board lease and stops both sessions; record observed disarm/Hold outcome rather than infer it | Run 06 Ctrl-C releases held lease; fresh board state unowned/disarmed/Hold |
| Lease loss | Operator performs a deliberate competing-owner takeover; old native authority clears and later traffic/reconnection does not reacquire | Run 08 passes historically; new Office activation timeouts block current acceptance until the prepared client is deployed and the real handoff repeats |
| WebRTC loss | Operator-induced real telemetry-link loss releases control; native peer recovery preserves healthy video and never reacquires | Run 13 natural telemetry gap revokes control, freshly clears board ownership/disarms, preserves video and recovers MAVLink without reacquisition; cause and controlled fault case remain open |
| Verification loss | Real loss of authoritative lifecycle reads stops the worker after fifteen seconds; record the fault method, last successful verification, lease release and terminal reason | Run 20 real expiry/HTTP 403 stops the worker and releases its held lease; fresh board state unowned/disarmed/Hold; exact last successful API-read timestamp unlogged |
| Video failure | Actual video failure while MAVLink stays available leaves telemetry/control working; record separate connection/counter evidence | Case 25 passes on 0.18.5: real camera loss, stable actual 2, same disarmed lease/telemetry and fresh parameters |
| REDCON 2 and 1→2 | Actual projection reaches 2; MAVLink remains usable and only video closes. A request for 2 satisfied by actual 1 does not pass this case | Case 25 passes live 1→2; case 26 passes fresh actual-2 entry with parameters, no video peer and zero video frames |
| REDCON 3/4 | Separate real transitions to 3 and 4 terminate the native session and release authority | Earlier actual 3 and run 09 actual 4 terminate/revoke native authority; post-loss/off board lease shadows stay stale |
| Device death | Actual DDEATH projection terminates the native session and releases authority; record how the operator produced death | Run 10 whole-TBot power-off produces DDEATH and native exit 0; authority cleared on preceding control timeout; board lease shadow stale |

Observe the initial control/parameter flow before planning fault induction.
Choose each live fault method with the operator and preserve device ownership
boundaries. Do not alter global Mac networking, IAM, device configuration or
board services merely to manufacture a failure. The old observation-only
`agent-live-tests` executable injects faults in its own process and acquires no
control; its results cannot fill these physical rows.

## Evidence and closeout

Keep dated operator action notes alongside native logs and read-only samples of
the `sparkplug` and `mavlink` shadows. Record service versions and field metadata
timestamps: reading a cached domain shadow is not fresh proof of a physical
event. The board's session/epoch and armed/mode observations complement QGC's
fresh parameter/vehicle state and the operator's direct wheel observations.

Match every Issue criterion to actual evidence. Missing transitions, failed
negotiation, cached parameters, interrupted runs and unresolved behavior keep
#167 open. Update this record and the Issue as results arrive. No production
publication or later cloud implementation can proceed on preparation alone.

Local execution uses the existing native build and
[QGC settings](../agent/README.md#local-qgroundcontrol). The prepared board repair
requires Alpine artifact validation, an explicit commit/push, operator-dispatched
immutable release and coordinated manual TBot maintenance before affected
physical repetition. It requires no rig/Office installation, AWS resource
mutation or firmware flashing. Scope ends at #167.
