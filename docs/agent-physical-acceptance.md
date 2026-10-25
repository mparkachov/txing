# Native physical acceptance — #167

Status, 2026-10-25: **open**. Real observation and parameter retrieval are
recorded. Two control runs were interrupted by loss of board capabilities.
No armed transition or motion is verified; remaining checks are pending.
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
captured in the read-only samples; the operator's result is still pending.

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
show that networking was reachable during the second interruption. No further
native run has started. The operator's normal Arm result from the interrupted
attempt is still needed to choose the next physical step.

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
the lifecycle rule or repairing the board within this acceptance issue.

## Cases and required observations

Each row remains pending until its actual logs, board state and operator
observations are recorded. Use separate named logs for separate runs. Retain
failed attempts and the source/executable identity for every retry.

| Case | Required physical evidence | Status |
| --- | --- | --- |
| Observation | QGC receives live telemetry; native operator receives/counts encoded video at actual REDCON 1; no control acquisition | Streams/QGC messages verified; full numeric GUI display unverified |
| Parameters and one control session | Fresh parameter retrieval after free-lease grant; operator arms, drives, stops input, disarms, re-arms and finally disarms; native grant remains continuous and board session/epoch unchanged throughout | Parameter names/values load; warning unresolved; no arm/drive/re-arm attempt |
| Office contention | Office acquires first; a fresh explicit agent run reports busy, does not displace Office and sends no uplink; after Office releases, the same agent run still does not acquire automatically | Pending |
| Client inactivity/disconnect | With control held and motion stopped, disable QGC heartbeat/traffic or disconnect its UDP link; board/native authority clears at the five-second client deadline; reconnecting never reacquires | Pending |
| Process interruption | Ctrl-C/SIGTERM on the foreground agent releases its real board lease and stops both sessions; record observed disarm/Hold outcome rather than infer it | Pending |
| Lease loss | Operator performs a deliberate competing-owner takeover; old native authority clears and later traffic/reconnection does not reacquire | Pending |
| WebRTC loss | Operator-induced real telemetry-link loss releases control; native peer recovery preserves healthy video and never reacquires | Natural outage revokes native authority without reacquisition; board-side expiry/recovery still unverified |
| Verification loss | Real loss of authoritative lifecycle reads stops the worker after fifteen seconds; record the fault method, last successful verification, lease release and terminal reason | Pending |
| Video failure | Actual video failure while MAVLink stays available leaves telemetry/control working; record separate connection/counter evidence | Pending |
| REDCON 2 and 1→2 | Actual projection reaches 2; MAVLink remains usable and only video closes. A request for 2 satisfied by actual 1 does not pass this case | Pending |
| REDCON 3/4 | Separate real transitions to 3 and 4 terminate the native session and release authority | Actual 3 terminates the native run; 4 and fresh board-side release evidence pending |
| Device death | Actual DDEATH projection terminates the native session and releases authority; record how the operator produced death | Pending |

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

Local rollout uses the existing native build and
[QGC settings](../agent/README.md#local-qgroundcontrol). No board/rig/Office
installation, AWS mutation, firmware flashing or automatic commit is required.
Scope ends at #167.
