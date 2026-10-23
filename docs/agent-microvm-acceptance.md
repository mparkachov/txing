# Disposable MicroVM acceptance — #165

Status, **2026-10-23: accepted within the current-stage fifty-minute limit**.
The operator's [duration decision](constraints/agent-session-limit.md) supersedes
both the previous eight-hour product budget and the extended #165 observation
past original one-hour role expiration. The earlier extended test failed and
remains recorded below; it is not relabelled as a successful expiration test.

The same C++ runtime built and ran in Frankfurt on Linux ARM64. Accepted image
`txing-agent-probe-165-c963a8c8a9df`, version `1.0`, build ID
`c963a8c8a9df7d4b6760bb244de017056e430b36fa18f6f03f17dce0ed47636d`,
is tied to ZIP SHA-256
`209bd78f25c2eb293b1dd6bbfe051436ee89ed7884f430aa5a84c50f28154287`.
AWS passed both ARM64 CTest targets, final snapshot-safe linking and the waiting
ready/validate hooks. The immutable package and image are preserved. All runtime
source matched that package at #165 closeout; its sole packaged-file difference
then was `agent/README.md`, updated to describe this accepted limitation.
Subsequent native QGroundControl work in #166 changes the application source;
that work needs a fresh image before future cloud use. This immutable image
and historical acceptance evidence remain the #165 revision.

The bounded re-audit uses **598 recorded status samples** inside fifty minutes
of actual seventh-VM service start. Its last sample is at 16:00:43.361 CEST,
49 minutes 55.262 seconds after launch. After native attachment reopening,
382 consecutive healthy unattached samples span **1910.438 seconds**, with
+33,013 telemetry messages and +56,961 video frames. Both counters increase at
every sample; both links stay connected, control stays false and maximum sample
gap is 5.015 seconds. Initial/reopened native probes pass with 371/345 telemetry
frames, H.264 metadata, pong and unauthorized-send rejection; ingress is
200/403/403 and selected device paths are relay-to-relay.

Credential generation advances to 2 at 15:45:50.819 CEST. Within the bounded
window, **892.542 seconds** of subsequent healthy media add 15,423 telemetry
messages and 26,604 video frames. External STS metadata records the actual role
assumptions and finite expirations; the SDK audit itself reports
`finiteExpiration=false`. Provider-call counts alone are not used. Secret scans,
operator termination and fresh read-only zero-active inventories pass.
The final audit is `tmp/issue-165/fifty-minute-stage-acceptance.json`; its
read-only analysis is `audit-fifty-minute-stage.py`.

**Known limitation:** the board's existing credential renewal recreates KVS
sessions about every fifty-five minutes. Its temporary loss of MAVLink
capability explains the later lifecycle shutdown closely, with the intermediate
projection inferred from source. An older board can reach this interruption
before a new agent has run fifty minutes. The ceiling is not an uninterrupted
service guarantee. Board renewal repair is deferred; the Wi-Fi/MMC kernel fault
remains separately tracked in #171 outside all milestones.

New disposable launch requests must use **3000 seconds** and retain absent idle
policy. The historical seventh request actually used 7200 seconds. Its samples
establish bounded feasibility, not live enforcement of a 3000-second cutoff;
controller/released-cloud duration-boundary acceptance remains later work.
A current review-only request is
`tmp/issue-165/run-microvm-review-c963a8c8a9df-50min.json`; no new run is needed
for this closeout. All seven launches have recorded termination, current
inventories have zero active probe VMs and both seventh-run ingress tokens are
removed. Retained artifacts/logs can still incur storage costs.

The sections below preserve historical observations and their then-current
acceptance requirements. Statements that the old extended gate remains open or
that a board-renewal scope decision is pending are superseded by the dated
fifty-minute decision above. This experiment adds no controller, lifecycle
trigger, production publication or QGroundControl bridge. It does not acquire
control. Implementation of later milestone issues remains separate.

## Sixth observation — interrupted; cleanup verified, 2026-10-22

The operator launched `microvm-3e082d6b-1d52-37c8-85a9-2e478347c4fa` at 13:44:33.421 CEST / 11:44:33.421 UTC using corrected image `txing-agent-probe-165-c963a8c8a9df`, version `1.0`. Actual Linux ARM64 execution, expected execution role, both managed public connectors, absent idle policy, two-hour cap and both independent relay-to-relay streams are verified. All 32 packaged source files still match; ZIP SHA-256 is `209bd78f25c2eb293b1dd6bbfe051436ee89ed7884f430aa5a84c50f28154287`. Initial native attachment passed with 364 telemetry frames, H.264 metadata, pong and unauthorized-send rejection; HTTP checks returned 200/403/403. Control was never acquired.

**The correction recovered a natural telemetry stall inside the MicroVM.** The counter stayed at 15,467 from 13:59:37.633 to 14:00:12.734 CEST. Status records `no MAVLink telemetry for 15 seconds` at 13:59:52.677, then a new telemetry connection; frames resume by 14:00:17.748. Video remains connected and grows by 367 frames across that sampled recovery. No worker restart, video reset or operator intervention is involved.

A later event stops both streams and board SSH. Last board health is 14:01:37 CEST, last received video 14:01:47.915, and the Mac SSH reader ends with `Timeout, server 192.168.0.10 not responding.` The operator confirms no state change and an unreachable board. At 14:03:30.512 the projection reports actual REDCON 3, target 1 and unavailable board/MAVLink/video. Authenticated application status subsequently confirms `phase=stopped`, `stopReason=device inactive or dead`, 17,024 telemetry messages, 11,550 video frames and control false. Service GetMicrovm still reported RUNNING after worker shutdown, so it is not used as evidence of working observation.

The preserved board prefix contains repeated brcmfmac Wi-Fi SDIO/backplane failures from 13:47:30, CMD53 write timeout -110 at 13:53:58, RXHEADER/recovery errors at 13:57 and 13:59, and firmware command timeout -110 at 13:59:43. The same boot ID and four service PIDs continue through the last health sample, with ample memory/storage. These are concrete leads in the board Wi-Fi/MMC path, not proof of a reboot, power loss or the final failure cause. Many SDK frame-drop warnings also occur before the outage; warning counts are not unique lost-frame counts.

This run records 226 decoded status samples and 17,746 final CloudWatch events. The final unattached sample interval is 842.405 seconds and includes both the recovered telemetry gap and later device outage; it is **not** a clean sixteen-minute window. Reopening was not reached in this attempt. Earlier-image reopening/unattached evidence remains historical. Credential generation stays 1; initial STS expiration is 14:44:33 CEST / 12:44:33 UTC, which this observation does not cross. **The full execution-role renewal gate remains open.**

The operator terminated this MicroVM at 14:06:12.826 CEST. Read-only GetMicrovm and complete inventories across both accepted runtime images verify all six probe VMs TERMINATED and zero active. The local reader has exited; its final stale-status alert is superseded by authenticated proof of worker shutdown. The local ingress token is removed. Final pattern scans of all captured application events, the native probe and board log find no ingress token, access-key pattern, credential value, private key, signed query or ICE password. Snapshot readiness/build evidence establishes the pre-run initialization boundary; scans do not directly inspect AWS-managed encrypted snapshot memory.

#165 stays open. The recovered full persistent capture now records the kernel Oops and continued board execution described below. Current archived capture: `/root/tbot-capture/20261022T075948Z-9c39619e`. Retrieval is complete; recovery reboot restored normal read-only-root/tmpfs logging. The board fault is separately tracked in #171; per user direction, #165 continues with current functionality and the accepted image. No automatic retry, controller/lifecycle automation, alternate host, board installation, Office change, custom service, AWS mutation by the agent or commit.

Evidence under `tmp/issue-165/`: `sixth-run-interrupted-evidence.json`, `sixth-run-first-natural-telemetry-recovery-evidence.json`, `sixth-run-final-status-samples.json`, `sixth-run-cloudwatch-final.json`, immutable board snapshots, `sixth-run-board-kernel-during-run.log`, `sixth-run-warning-summary.json`, `sixth-run-role-api-metadata.json`, `sixth-run-final-diagnostic-secret-scan.json`, `sixth-run-cleanup-evidence.json`, `sixth-run-terminated-runtime.json` and both final image inventories.

## Recovered board archive — Wi-Fi/MMC kernel Oops established

The operator recovered the TBot through the normal Office REDCON 4 → 1 flow and saved the complete persistent capture. The gzip CRC and all 24 archive members validate. SHA-256 is `a037e5a6c22f12ef6324f55d01846522b1550e161d97879a97dec84109065e46`; the original archive is retained unchanged.

The missing event is a kernel NULL-pointer Oops at **14:01:48 CEST / 12:01:48 UTC**, fault address `0x38`, PC `bcm2835_mmc_transfer_dma+0x88/0x248`, on `brcmf_wq/mmc1:0001:1 brcmf_sdio_dataworker [brcmfmac]`. The call trace traverses board Wi-Fi SDIO/MMC packet transmission. It aligns with the last received video at 14:01:47.915 and first board socket-send timeout at 14:01:48.629. This establishes a kernel failure in the Wi-Fi/MMC path at the outage; the initiating hardware/firmware/timing trigger is still unresolved.

The board keeps executing afterward: stored KVS logs continue network/signaling/DNS timeouts until at least 14:11:27.042, 579 seconds after the Oops. The final stored health timestamp is 14:01:58; its record stops before wireless-statistics/PID output, consistent with a blocked network-statistics read rather than proof of immediate whole-system shutdown. No kernel-panic message is recorded. A later camera timeout does not establish a camera-originated outage.

Recovery changes boot ID from `9c39619e-43ab-4dcf-81d2-8f1c18256fad` to `07961cd6-d911-49db-8c72-639f96d7b6dd`. Root and boot are read-only and `/var/log` is tmpfs, so the temporary persistent-logging maintenance state has ended through the reboot. The archived capture remains on storage.

Read-only inventory confirms both running and installed kernel 6.18.44-0-rpi / linux-rpi 6.18.44-r0 on Alpine 3.24.1. The available v3.24 kernel is 6.18.58-r0; boot firmware is installed 1.20260810-r0, available 1.20260915-r0. The affected driver file in both official Alpine patch sets is identical, SHA-256 `d2bbd5afc2faa31b8839aa8071d2464aa4361c9ae86824ab0f7f43e2851a5ef6`; the live Raspberry Pi branch gives the same file. A stock update has not been established as a driver fix. Source review suggests a request/completion synchronization race around DMA setup and `host->data`; this remains a hypothesis awaiting compiled mapping and a tested repair.

The user moved board remediation to [#171](https://github.com/mparkachov/txing/issues/171), outside all milestones, and directed continuation of #165 with current functionality. The existing kernel and boot settings remain. The prepared SDIO trial is unselected and is not part of this acceptance run. No guessed DMA-disable option, custom service, package update, firmware flash, new cloud launch or custom kernel has been applied.

Detailed report: `tmp/issue-165/board-wifi-kernel-oops-report.md`. Evidence: `board-after-sixth-archive-evidence.json`, `board-after-sixth-kernel-crash-evidence.json`, `board-after-sixth-kernel-oops.log`, extracted selected logs, `board-upstream-driver-source-comparison.json` and `board-20261022T080227Z/board-os-inventory-after-sixth.txt`. Reviewed optional diagnostic: `operator-sdio-clock-trial.md`. #165 remains open for actual execution-role renewal; all six MicroVMs remain terminated and no later cloud implementation proceeds.

## Seventh launch preflight — historical

Per the user's direction, board Wi-Fi/MMC remediation is tracked in #171 outside all milestones; it is not being implemented as part of this issue. The recovered board keeps its existing kernel and firmware settings. The archived evidence remains preserved and normal read-only-root/tmpfs logging is restored.

Fresh 2026-10-22 14:36 CEST preflight confirms actual REDCON 1 and unexpired board/MAVLink/video capabilities, accepted `c963a8c8a9df` image version `1.0` SUCCESSFUL/ACTIVE, unchanged exact role policy, all 32 source files matching the package and all six prior VMs terminated. The seventh launch request has a unique observation-7 token and retains managed public networking, no idle policy and a 7200-second hard cap. No image rebuild, stack update, writable-root capture or board configuration change is required.

Reviewed operator instructions: `tmp/issue-165/operator-seventh-run.md`; exact request: `run-microvm-review-c963a8c8a9df-observation-7.json`; read-only capture: `observe-seventh-run.py`. The seventh MicroVM was launched and terminated as recorded below. Attachment reopening and actual renewed-role use pass; media beyond initial credential expiration remains open. The separate board issue does not waive this acceptance criterion or authorize later cloud implementation. No AWS mutation, deployment or commit by the agent.

## Seventh observation — interrupted; cleanup verified, 2026-10-22

The operator launched `microvm-84542f55-8286-3288-b11c-4b95b72bd398` at 15:10:48.099 CEST / 13:10:48.099 UTC using accepted `c963a8c8a9df` image version `1.0`. The intended execution role, managed public ingress/egress, 7200-second cap, absent idle policy and all 32 frozen source hashes are verified. Initial attachment passes with 371 telemetry frames; reopening passes with 345 frames, H.264 metadata, pong and unauthorized-send rejection. HTTP checks return 200/403/403. The preceding unattached interval is 962.728 seconds over 193 samples, with one naturally recovered telemetry-silence episode while video continues. Control remains false.

**Real execution-role refresh is recorded.** Generation 2 first appears at 15:45:50.819 CEST. Both links stay connected over the following 1,128.215 seconds of sampled media, adding 19,485 telemetry messages and 33,544 video frames. CloudTrail independently records a new role assumption at 15:41:00 CEST, expiration 16:41:00 CEST, and successful `DescribeSignalingChannel` / `GetSignalingChannelEndpoint` calls at 16:04:40 CEST using that new session. These records establish an actual refreshed tuple and its use for signed AWS calls. The SDK itself reports `finiteExpiration=false`; external STS metadata supplies the deadlines.

The worker then stops with `device inactive or dead`, confirmed by authenticated HTTP at 16:08:25 CEST after the operator refreshed the expired ingress token. The last CloudWatch status is 16:04:39.034 CEST, with 55,393 telemetry messages and 95,440 video frames; last video receipt is 16:04:36.127. Initial role expiration is 16:10:48 CEST, **371.873 seconds after the last video**. No live-media sample crosses that deadline. The agreed original-expiration check remains open despite the genuine earlier renewal. Service state RUNNING after worker shutdown is not accepted as active observation.

The operator confirms no REDCON change around the stop. A later projection at 16:04:48.504 CEST reports actual REDCON 1 and available board/MAVLink/video, with unchanged command/target. Intermediate projections were not retained; transition-window rig/device-filtered witness lookups are empty. The follow-up board capture below records scheduled IoT credential renewal and KVS session recreation in the shutdown window, with unchanged boot ID. Source review explains how that restart temporarily removes MAVLink capability and leads to REDCON 3. The intermediate lifecycle payload remains inferred. This run does not establish another Wi-Fi/MMC kernel fault. The reviewed board-renewal correction needs a scope decision; authoritative lifecycle shutdown is unchanged.

Final capture contains 2,088 CloudWatch events and 645 decoded status samples. Pattern scans cover all captured application events, both native probes, the authenticated stopped status and allowlisted role metadata. They find no access-key pattern, credential value, private key, signed query, ICE password or either exact ingress token. This is not direct inspection of AWS-managed encrypted snapshot memory; hook/build evidence establishes the pre-run initialization boundary.

The operator terminated the seventh VM at 16:16:53.415 CEST. Read-only GetMicrovm confirms TERMINATED. Complete current inventories across both accepted runtime images contain four terminated entries and zero active VMs; the first three launches are no longer listed, with their earlier termination evidence retained. Termination has been recorded for all seven launches. Both seventh-run ingress token files are removed and the local reader has exited. Stack, images, source packages and logs remain retained.

#165 stays open for media beyond original role expiration. No eighth launch, board deployment, Office change, lifecycle automation, AWS mutation by the agent or commit. Board kernel remediation remains separately tracked in #171, outside all milestones.

Evidence under `tmp/issue-165/`: `seventh-run-interrupted-evidence.json`, `seventh-run-observation-audit.json`, `seventh-run-cloudwatch-final.json`, `seventh-run-final-status-samples.json`, `seventh-run-role-api-metadata.json`, `seventh-run-http-after-capture-gap.json`, `seventh-run-sparkplug-at-capture-gap.json`, `seventh-run-final-diagnostic-secret-scan.json`, `seventh-run-cleanup-evidence.json`, `seventh-run-terminated-runtime.json` and both final image inventories.

## Seventh board capture — scheduled renewal interrupts lifecycle

The operator saved the requested read-only capture at **16:24:54 CEST / 14:24:54 UTC**. Boot ID remains `07961cd6-d911-49db-8c72-639f96d7b6dd`, matching recovery after the sixth run; uptime is 2:11 and both daemon/KVS services are started. The daemon log is empty, but the KVS log includes the incident. The combined capture is 682,383 bytes, SHA-256 `aeb68a03d6b983fb3794ef0dad429c48ccbe76a411d6044cc5eb476a5acf130f`; credential/private-key/signed-query/ICE-password pattern scans find zero matches. No new kernel crash is established.

Read-only role-alias inspection confirms board IoT credentials last 3600 seconds. Allowlisted CloudTrail metadata records successful board-role assumptions at **14:14:37, 15:09:37 and 16:04:37 CEST**, exactly 55 minutes apart, plus another assumption at 16:04:40. Board logs close/free KVS peers at 16:04:40.152 and 16:04:42.843 and create new signaling clients at 16:04:40.677 and 16:04:43.149. The exact seventh agent peer (`agent-17926746499148450`) is logged disconnecting in this window. Browser viewers reconnect afterward. The board role is distinct from the already-proven renewed MicroVM execution role.

The source explains this sequence: board KVS credentials are static within a session, so runtime refresh five minutes before expiration stops/recreates sessions. The MAVLink loop explicitly reports `ready=false` during replacement; the daemon publishes MAVLink capability false. TBot REDCON 1/2 both require MAVLink, so the rig derives REDCON 3 and the agent stops under its existing inactive/dead rule. This is a strong explanation for the seventh shutdown. **Renewal, session recreation, matching peer disconnect, unchanged boot and stopped worker are recorded; the intermediate capability/REDCON payloads remain inferred from source, not captured.** This capture does not independently verify deployed binary hashes.

A routine seventy-minute retry would cross the same 55-minute board renewal cycle. On 2026-10-23 the operator chose a fifty-minute current-stage ceiling instead of expanding #165 into board renewal repair. The repair proposal is deferred; the scope question is resolved by the [duration decision](constraints/agent-session-limit.md). The original-expiration test is superseded, not passed. The bounded audit above establishes #165 feasibility. Kernel remediation remains in #171 outside all milestones.

Evidence: `tmp/issue-165/seventh-board-renewal-interruption-evidence.json`, `seventh-board-iot-role-renewal-metadata.json`, `seventh-board-session-transitions.json`, `seventh-board-lifecycle-capture-audit.json`, original `seventh-board-lifecycle-current.log`, and reviewed `seventh-board-renewal-findings.md`.

## Runtime and snapshot boundary

`txing-agent --microvm --ca <verified-pem>` starts only the hook and attachment
listeners. Before `/run`, AWS SDK initialization, provider construction, unique
run identity and KVS initialization have not occurred. `/ready` and `/validate`
report that state without consulting credentials or opening device sessions.
The pinned KVS SDK's bounded JSON tokenizer parses the initial string envelope;
AWS JSON/configuration facilities initialize only after a valid `/run`.

The `/run` payload is the AWS envelope containing `microvmId` and a
`runHookPayload` string. That string has exactly `thingId` and `region` fields;
this experiment requires `eu-central-1`. The application starts one worker
using the actual `AwsDevice`, default credential provider chain, process-owned
KVS lifetime and `Session`. Repeated identical hooks do not restart it; changed
identity/payload, malformed hooks, build hooks after initialization, and resume
are rejected. Terminate/suspend close the device sessions. Suspension and
automatic resumption must be disabled at launch.

The image uses the AWS-provided snapshot-compatible AL2023 base, pinned by its
ARM64 container manifest. Snapshot-safe OpenSSL is selected by RPM ownership,
copied explicitly, and verified in the final link resolution. SRTP/curl/zlib
come from AL2023; WebSockets, usrsctp and log4cplus use exact upstream commits.
The existing AWS SDK and shared KVS pin remain unchanged. The image build must
compile and test natively for ARM64 before it can pass. The final image contains
the application, libraries, verified trust roots and provenance, runs as UID
10001, and contains no source checkout, local AWS profile or injected secret.

AWS documentation:
[image building](https://docs.aws.amazon.com/lambda/latest/dg/microvms-images.html),
[snapshot/OpenSSL requirements](https://docs.aws.amazon.com/lambda/latest/dg/microvms-images-snapshots.html),
[hooks and launching](https://docs.aws.amazon.com/lambda/latest/dg/microvms-launching.html),
[networking/authentication](https://docs.aws.amazon.com/lambda/latest/dg/microvms-networking.html),
[roles](https://docs.aws.amazon.com/lambda/latest/dg/microvms-security.html).
The docs establish the API contracts, not KVS connectivity or role refresh.

## Recorded image attempts — 2026-10-21

The operator-created `txing-agent-probe-165` stack reached `CREATE_COMPLETE`.
Image `txing-agent-probe-165-fca66c894955`, version `1.0`, reached `FAILED` at
08:49:50 UTC. Its container build rejected simultaneous minimal/full curl
providers in both stages. No application compilation or runtime acceptance
occurred. Preserve this image's logs and package as failure evidence.

The corrected Dockerfile explicitly swaps `libcurl-minimal` for `libcurl-full`
and `curl-minimal` for `curl-full` in both stages before installing dependencies,
following the [AL2023 package guidance](https://docs.aws.amazon.com/linux/al2023/ug/curl-minimal.html).
This changes the source-derived build identifier. Reuse the existing stack,
upload the newly packaged context, and create its new source-derived image name;
the failed image and old S3 artifact do not need to be overwritten or deleted.
The replacement build must still prove Linux compilation and all later gates.

The second image, `txing-agent-probe-165-f1eaabeaae78`, version `1.0`, reached
`FAILED` at 08:59:37 UTC. All three native dependencies compiled, but WebSockets
installed under its build directory. Its untyped `LWS_INSTALL_LIB_DIR=lib64`
argument became an absolute cache path. The corrected argument is
`LWS_INSTALL_LIB_DIR:PATH=lib64`; a configuration-only reproduction verifies
that this generates an install under the intended prefix. The Dockerfile also
checks all three installed libraries before configuring the agent.

The first local Lima build (`13e59d2fffa1`) passed the library-path checks and
compiled the AWS clients, then failed KVS configuration because WebSockets'
pkg-config metadata remained under `lib/pkgconfig`. The corrected layout uses
typed `LWS_INSTALL_LIB_DIR:PATH=lib` with `LIB_SUFFIX=64`, so both libraries and
metadata install under `lib64`. A generated-install-script/pkg-config check
verifies both paths; the Dockerfile checks `pkg-config --modversion libwebsockets`
before the SDK build.

The next local build (`cca566739f4d`) compiled the KVS SDK but failed while
staging its producer/PIC support archives, which AL2023 installs in `lib64`.
An agent-private CMake step now stages those archives under `lib` before the
existing shared helper copies them. The shared SDK resources and pin are
unchanged. The replacement local build and packaged-container checks pass.

Current context: build ID
`5db8fe4d03347d3a9133eb9e8ca2d32929d1d782b5b42e5a274e7d60cec01443`,
zip SHA-256
`661418fdda54d56ff8c0db4427481ea47ea11767ae260d34ac58d5ffd252cda2`.
The exact 32-file source/hash audit and local validation pass. When creating a
changed context, reuse the first block's stack-output variables and start from
`probe_build_id=$(cat tmp/agent-probe-package/build-id.txt)` through its
`create-microvm-image` command. Do not reuse either failed image's name/token.
Rerunning only the final create command keeps old shell variables: a recorded
retry still targeted `f1eaabeaae78` and returned `ConflictException`. Refresh the
build ID, image name, artifact URI and client token together for each new context.

The operator subsequently uploaded this exact package and created
`arn:aws:lambda:eu-central-1:453102798330:microvm-image:txing-agent-probe-165-5db8fe4d0334`.
A read-only download of the S3 artifact matches the local zip checksum. The
12:01:49–12:10:06 UTC image build compiled the same C++ runtime, passed both
Linux CTest targets (2.91 seconds), verified AArch64 and final snapshot-safe
OpenSSL resolution, and validated the source hashes. Image hook logs report
`waiting for /run` with listeners 8080/8081; successful snapshot validation did
not initialize a runtime identity, credentials or device sessions. Image/version,
build and hook evidence is preserved in `tmp/issue-165/image-5db8fe4d0334.json`,
`image-versions-5db8fe4d0334.json`, `image-build-5db8fe4d0334.log`,
`image-hook-logs-5db8fe4d0334.json` and `uploaded-package-5db8fe4d0334.json`.
Use this successful version for the prepared launch; another image build is
unnecessary unless its packaged source changes.

## First runtime attempt — 2026-10-21

The operator launched `microvm-06ea1424-d6d9-3ed2-9d9e-a9952e784b4d` at
14:25:20 CEST (12:25:20 UTC), using the accepted image/version, generated execution
role, both managed public connectors, a 7200-second cap and no `idlePolicy`.
CloudWatch startup status identifies the expected build, device, region and
actual MicroVM ID. CloudTrail confirms the execution role successfully called
`DescribeThing` and resolved the correct account-specific IoT ATS endpoint.

The `sparkplug` named-shadow read returned `ForbiddenException`/403. The worker
stopped at its fifteen-second unverified-lifecycle deadline, with zero telemetry
messages and video frames. The hosting process remained reachable and the service
still reported `RUNNING`; neither service state nor the operator's
14:35:05–14:55:16 CEST wait proves sustained device observation. Authenticated
`/status` returned 200 and recorded `phase=stopped` with
`stopReason=lifecycle unverified for 15 seconds`. The WebSocket probe failed
after observation had stopped. No successful manual-attachment traffic is claimed.

Unauthenticated 8081 and token-authenticated forbidden-port 8080 requests both
returned 403. Credential status reported one temporary generation and
`finiteExpiration=false`; real refresh remains unverified. Preserve the first
run's responses and logs under `tmp/issue-165/`, including
`runtime-current.json`, `runtime-cloudwatch-1256.json`, `live-status-1256.json`,
`first-run-describe-thing-cloudtrail.json` and `first-run-endpoint-cloudtrail.json`.
Following the operator handoff, read-only `GetMicrovm` inspection confirmed
`TERMINATED`; the response is preserved in `runtime-first-run-latest.json`.

### Correct the named-shadow permission before retrying

AWS documents the named-shadow resource as
`arn:aws:iot:REGION:ACCOUNT:thing/THING/SHADOW`, including the shadow name; see
[AWS IoT Core action resources](https://docs.aws.amazon.com/iot/latest/developerguide/iot-action-resources.html).
The original probe policy combined `DescribeThing` and `GetThingShadow` on the
Thing ARN, which does not match the named shadow. `agent/probe/stack.yaml` now
keeps `DescribeThing` on `thing/${ThingId}` and grants only `GetThingShadow` on
`thing/${ThingId}/sparkplug`. It adds no write access or access to another device.

Read-only IAM simulation confirms the deployed policy denies the named-shadow
resource. The corrected policy permits that exact read and denies reads of
another shadow/device and all tested shadow writes. CloudFormation template
validation passes. Results are in `tmp/issue-165/named-shadow-policy-validation.json`
and `named-shadow-template-validation.json`.

After the failed MicroVM is `TERMINATED`, the operator must deploy the corrected
template to the existing disposable stack, then launch a fresh run with a new
idempotency token. The same successful image/version can be reused: the IAM role
is external to the image, and all C++ runtime/build/probe sources still match
the frozen package. Only the stack template differs; that comparison is recorded
in `tmp/issue-165/runtime-source-match-after-policy-fix.json`. Exact current-account
deployment and second-run commands are prepared in
`tmp/issue-165/operator-named-shadow-retry.md`. Preserve the first run's files;
the retry uses `run-second.json` and `proxy-token-second`.

## Second runtime attempt — 2026-10-21

The operator's stack update reached `UPDATE_COMPLETE` at 15:12:38 CEST
(13:12:38 UTC); stack events show only `ExecutionRole` updated. The deployed
policy now matches the exact `sparkplug` resource. The operator launched
`microvm-504a6463-c261-320a-aa8b-5b602c635d41` at 15:13:24 CEST using the same
accepted image/version, managed public connectors, two-hour cap and no idle
policy. Its restored identity differs from the first run, and CloudTrail again
confirms actual execution-role use.

Both independent KVS sessions connected. SDK selected-pair records show
**relay → relay for both sessions**, rather than only TURN allocation attempts.
The operator boundary received real MAVLink and encoded H.264 with byte counts,
presentation timestamps and receipt timestamps. The C++ attachment probe passed
from 15:15:20 to 15:15:40 CEST: 346 binary telemetry frames, H.264 metadata,
ping/pong and rejection of a framed send without control. Control stayed false.
Authenticated status returned 200; no-auth 8081 and forbidden-port 8080 returned
403. This resolves the previously failed initial attachment attempt.

After detachment, counters advanced to 3,092 telemetry messages and 5,349 video
frames. Last video receipt was 15:16:31 CEST. Both peers then disconnected and
retried offers without an answer. A later projected lifecycle sample at
15:18:38 CEST reported actual REDCON 3, target 1 and unavailable board/MAVLink/video
capabilities. Authenticated status subsequently confirmed `phase=stopped` and
`stopReason=device inactive or dead`. The initial peer-disconnect cause remains
unproven; the later inactive projection alone does not establish that cause.
The required uninterrupted interval beyond fifteen minutes has not passed.

Only one credential generation was observed. CloudTrail expiration metadata
confirms the actual temporary session was issued at 15:13:24 CEST for 3600
seconds, expiring at 16:13:24 CEST. The SDK audit reports
`finiteExpiration=false`; it does not supply that expiration itself. Only role
and expiration metadata was retained from the STS lookup. Credential renewal
remains unverified. A stable retry should budget roughly seventy minutes to
cover renewal of the one-hour session and successful subsequent traffic, while
retaining the two-hour hard cap. Elapsed time or increasing `providerCalls`
does not prove renewal.

Evidence is in `tmp/issue-165/second-run-acceptance-evidence.json`,
`second-run-cloudwatch-current.json`, `second-run-status-samples.json`,
`second-run-attachment-initial.log`, `second-run-attachment-window.json`,
`second-run-after-lifecycle-status.json`, `second-run-*-status.txt`,
`second-run-describe-thing-cloudtrail.json`,
`second-run-assume-role-expiration-metadata.json`,
`execution-role-policy-retry-current.json` and
`stack-named-shadow-update-events.json`. The operator confirmed the TBot dropped
on its own, then terminated the second MicroVM. `GetMicrovm` records
`TERMINATED` at 15:33:47 CEST, and the final image-filtered inventory confirms
both attempts terminated with zero active probe runs. Images, source packages,
logs and the disposable stack are retained for a possible retry; see
`operator-cleanup-current.json`. Restore stable actual REDCON 1 before another
fresh operator-run observation; the stopped application cannot be restarted
with the same Run hook.

### Device access follow-up

The operator reports that the board is no longer pingable and local access is
unavailable. Its live retained `txings/tbot-8yzfgj/capability/v2/state` message
is absent (`GetRetainedMessage` returns `ResourceNotFoundException`). The board
contract uses a 150-second capability TTL and 60-second heartbeat; the rig also
ignores capability evidence older than 150 seconds. Missing fresh board
capabilities is consistent with the later REDCON 3 projection, but does not
identify the original peer-disconnect or network/power failure.

The durable `board`, `video` and `mavlink` shadows still contain older positive
values. Their unchanged state is not current availability evidence; see
[board retained-state freshness](components/board.md#retained-aws-iot-topics).
No TBot CloudWatch log group was found, and the rig's latest CloudWatch entries
precede the outage, so those logs cannot supply the missing board-side diagnosis.

Read-only STS metadata shows successful board-role credential issuance at
15:10:09/15:10:11 CEST, expiring one hour later. This does not prove every board
consumer refreshed, identify the outage cause, or satisfy the separate C++
agent credential-renewal criterion. Retained metadata contains no credential
values. Evidence: `drop-*-shadow.json`, `drop-retained-capability-error.txt`,
`drop-rig-log-streams.json`, `tbot-log-group-search.json` and
`drop-board-renewal-expiration-metadata.json` under `tmp/issue-165/`.

The operator subsequently used the normal REDCON 4 → 1 flow and restored video.
Read-only preflight again confirms actual REDCON 1 and available board/MAVLink/video.
The board uses a read-only root and the operator reports no preserved local logs;
the outage cause remains unproven. A fresh third-run request and operator commands
are ready in `tmp/issue-165/operator-third-run.md`. They reuse the accepted image
and deployed policy, retain the two-hour cap, and use separate third-run evidence
files. No board, rig, firmware or agent behavior was changed on an unproven
diagnosis. The sustained-operation/renewal gate remains open and later cloud
implementation remains stopped.

## Third runtime and overnight pause — 2026-10-21

The third restored runtime, `microvm-01e14344-ff3b-3dd1-b84e-0fca913ae68c`,
ran from 15:53:27 to 16:12:48 CEST (13:53:27–14:12:48 UTC). It reused the
accepted image/version and corrected role, both managed public connectors,
the two-hour cap and no idle policy. Both selected ICE pairs were relay → relay.
The initial native WebSocket probe passed with 349 binary telemetry frames,
video metadata, ping/pong and unauthorized-send rejection. No-auth and
forbidden-port requests returned 403; control was never acquired.

Final CloudWatch evidence contains 182 consecutive healthy, unattached samples
spanning **907.575 seconds** (15 minutes 7.575 seconds). Both connection states
remained open; telemetry and video counters increased at every sample, with a
maximum status gap of 5.015 seconds. Last recorded totals were 19,884 telemetry
messages and 34,306 H.264 frames. This satisfies the duration criterion, including
operation without a human attachment. It does not prove credential renewal or
successful attachment reopening: the operator ended the run before either was
exercised. Credential generation remained 1. The stop was an explicit operator
pause, not an observed device failure.

Read-only `GetMicrovm` confirms termination at 16:12:48 CEST. The image-filtered
inventory contains all three attempts as `TERMINATED`, with zero active runs.
The local capture process has exited and its third-run ingress token was
removed. Image/version, stack, source packages and logs are deliberately retained
for retry; they can continue to incur storage costs. No automatic overnight
runner or cleanup automation was installed, and no device state was changed.

Evidence: `tmp/issue-165/third-run-pause-evidence.json`,
`third-run-cloudwatch-final.json`, `third-run-final-status-samples.json`,
`third-run-terminated-runtime.json`, `third-run-final-inventory.json` and the
initial attachment/ingress records. A pattern scan of final runtime logs and
initial probe output found no ingress token, AWS access-key pattern, credential
value, signed URL or ICE password; this is not an inspection of managed snapshot
memory. The restart handoff is `tmp/issue-165/pause-handoff.md`.

On resumption, verify fresh actual REDCON 1 and board/MAVLink/video availability,
the image/version, deployed role and absence of active probe runs. Reuse the
accepted image unless its packaged sources change. A fresh fourth-run request
and separate evidence paths are prepared in `tmp/issue-165/operator-fourth-run.md`;
do not rerun the third run's idempotency token or reuse its terminated endpoint.
Budget roughly seventy minutes for actual execution-role renewal and successful
subsequent traffic, plus attachment reopening. The operator must launch the new
run, mint its token and terminate it afterward. #165 stays open, with subsequent
cloud implementation stopped.

## Fourth runtime — 2026-10-22

Fresh preflight confirms actual REDCON 1, fresh retained board/MAVLink/video
capabilities, accepted image `1.0` still `SUCCESSFUL`/`ACTIVE`, the corrected
execution-role policy, and all three earlier runs `TERMINATED`. The exact package
checksum and 31 packaged runtime/build/probe source files still match; only the
external IAM template differs. No image rebuild or stack update was needed.

The operator launched `microvm-9ee54b10-f3fb-3b67-a12c-facd31a25d93` at
08:45:23 CEST (06:45:23 UTC), using the accepted image, managed public connectors,
a 7200-second cap and no idle policy. Both selected ICE pairs are relay → relay.
The initial native attachment probe passed from 08:46:18 to 08:46:38 CEST with
347 telemetry frames, H.264 metadata, pong and unauthorized-send rejection.
Authenticated HTTP returns 200; no-auth and forbidden-port checks return 403.
Control was never acquired.

Metadata-only STS records confirm the initial execution-role session's one-hour
expiration at 09:45:23 CEST (07:45:23 UTC). The read-only
capture recorded a healthy unattached interval beyond sixteen minutes, followed
by successful native attachment reopening at 09:02:57–09:03:17 CEST. The reopening
probe received 345 telemetry frames, H.264 metadata and pong, and rejected an
unauthorized send without acquiring control. Both device sessions continued
afterward. The audited interval spans 962.853 seconds over 193 samples, with a
maximum gap of 5.017 seconds; both counters increased at every sample and both
links stayed open.

Last video arrived at 09:04:28.040 CEST. Both links reported loss at 09:04:58,
then repeatedly sent offers without receiving answers. At 09:05:28.771 CEST the
runtime recorded credential generation 2, approximately sixty seconds after
last media. CloudTrail records eight successful KVS API calls after that
generation change using the expected execution role. Its recorded session
creation time is still 08:45:23 CEST; the STS lookup has not established a newly
issued session. A tuple change and successful API calls are real evidence, but
do not prove resumed telemetry/video after renewal.

At 09:06:18.511 CEST the TBot projection reported actual REDCON 3, target 1 and
unavailable board/MAVLink/video. The live retained capability message is absent.
Authenticated status subsequently confirms `phase=stopped` and
`stopReason=device inactive or dead`, with 19,710 telemetry messages and 34,234
H.264 frames. Control remained false. The initial board/media failure cause is
unproven; neither the later projection nor later credential change establishes
that cause. The worker's stop on authoritative inactivity is expected behavior.

The local capture has exited. Its initial stale-status report was only an
observation gap; the later authenticated application status establishes the
actual worker stop. The operator confirms that the TBot dropped on its own,
its board is unreachable, and local/serial access is unavailable. No matching
board CloudWatch log group was found; the rig's newest log events precede the
outage. Current evidence cannot distinguish board power, kernel, networking or
service failure. Preserve local/serial boot and network evidence when access
becomes available, before power-cycling if possible. Read-only console commands
are prepared in `tmp/issue-165/operator-board-outage-check.md`. For the next
instrumented recovery/retry, follow the
[persistent TBot outage-capture procedure](tbot-outage-capture.md): retain local
system/service logs on storage and stream a second copy to the Mac before
starting another cloud observation.

The operator terminated the fourth MicroVM at 09:14:43.855 CEST
(07:14:43.855 UTC). Read-only `GetMicrovm` confirms `TERMINATED`, and the complete
image-filtered inventory contains all four attempts as `TERMINATED`, with zero
active runs. The fourth ingress token was removed locally. Accepted image,
failed images, source packages, stack and logs are deliberately retained for
retry and can incur storage charges. At that checkpoint no fifth run had been
prepared or launched. The instrumented fifth observation below followed board
recovery and persistent logging. Subsequent cloud implementation remains stopped.

Evidence: `tmp/issue-165/fourth-run-preflight-*.json`,
`fourth-run-frozen-source-audit.json`, `fourth-run-initial-evidence.json`,
`fourth-run-role-expiration-metadata.json`, `fourth-run-cloudwatch-initial.json`,
`fourth-run-observation-progress.json`, `fourth-run-reopening-evidence.json`,
`fourth-run-interrupted-evidence.json`, `fourth-run-after-drop-status.json`,
`fourth-run-after-generation-api-metadata.json`,
`fourth-run-cloudwatch-after-drop.json`, `fourth-run-cleanup-evidence.json`,
`fourth-run-terminated-runtime.json` and `fourth-run-final-inventory.json`.
Incremental raw batches, decoded
samples and an atomic read-only capture checkpoint are stored separately from
the earlier attempts. No production runtime or device behavior changed.

## Fifth runtime with persistent board capture — 2026-10-22

Fresh preflight again confirms actual REDCON 1, live retained board/MAVLink/video
capabilities, accepted image `1.0` ACTIVE/SUCCESSFUL, the unchanged corrected
execution role, unchanged 31 packaged runtime/build/probe files, and all four
earlier MicroVMs terminated. The operator launched
`microvm-f2825144-c049-30df-93d9-92d70dddf102` at 10:09:10 CEST
(08:09:10 UTC), with the same managed public connectors, absent idle policy and
7200-second hard cap.

Both real streams connected with selected relay → relay pairs. The initial
native WebSocket probe passed at 10:10:20–10:10:41 CEST with 353 telemetry frames,
H.264 metadata, pong and unauthorized-send rejection, without acquiring control.
Authenticated HTTP returned 200; no-auth and forbidden-port checks returned 403.
The operator confirms persistent board capture at
`/root/tbot-capture/20261022T075948Z-9c39619e`, with the board health sampler and
Mac log reader both running. The Mac copy is available inside the workspace at
`tmp/issue-165/board-20261022T080227Z/board-live.log`; no agent SSH connection was
made. Its health samples retain one boot ID and the same four service PIDs.

Attachment reopened successfully at 10:27:03–10:27:24 CEST: 342 telemetry frames,
H.264 metadata, pong and unauthorized-send rejection. The preceding unattached
window contains 195 consecutive healthy samples spanning 972.756 seconds,
maximum gap 5.015 seconds, with both counters increasing at every sample.

The provider records credential generation 2 at 10:29:15.578 CEST. Over the next
205.586 seconds, telemetry increases by 3,525 messages and video by 5,545 frames,
with both connections open. The SDK continues to report `finiteExpiration=false`;
external initial STS metadata supplies the original 11:09:10 CEST expiration.
Do not claim that original expiration has been crossed or substitute provider
call counts for the actual generation change.

The run then exposes a functional failure: the telemetry counter reaches 23,494
by 10:32:41 CEST and stops increasing, while video, the worker and board health
samples continue. Authenticated HTTP at approximately 10:39 CEST confirms this
state independently of CloudWatch, with control false. The Sparkplug projection
still reports actual REDCON 1 and target 1. An open connection-state enum alone
therefore does not establish live telemetry.

The board kernel records Wi-Fi SDIO receive errors at 10:26:55, a transmit error
at 10:32:13, and failed backplane access and receive recovery at 10:32:38–43.
At 10:34:59 it reports a warning in `bcm2835_mmc_transfer_dma` from the
`brcmf_sdio_dataworker` workqueue, followed by `CMD53 sg block write failed -110`
and KVS socket-send timeouts. This is a concrete board Wi-Fi/MMC failure lead;
it does not yet prove the cause of the telemetry stall or prior complete outages.
The warning is later than the start of the telemetry stall. The board is a
Raspberry Pi Zero 2 W Rev 1.0, kernel `6.18.44-0-rpi`, BCM43430/2 firmware
`9.88.4.77`. The captured health samples show ample memory/storage and unchanged
service PIDs; absence of OOM, panic or undervoltage messages does not rule out
other hardware or power faults.

The operator clarifies that the board remains available and was also available
in the previous run. Earlier reports recorded transient unreachability; those
reports do not establish a reboot or loss of board power. Diagnose board
reachability, video reception and each MAVLink peer separately. In this fifth
run, continued health samples, unchanged boot ID/PIDs and growing video prove
that the telemetry stall coexists with an available board.

The saved live archive is readable and gzip-complete, with 24 members including
baseline, health, system and service logs. It remains named
`board-capture-live.tgz.partial`; preserve that name and the original bytes.
It is a nonquiescent capture, so it does not claim an atomic final snapshot of
files that were still changing. The baseline reports TBot `0.18.12` and KVS
master `0.18.2`, matching repository version files. Daemon, MAVLink and KVS
OpenRC scripts match repository hashes; the ArduPilot script differs from the
repository and the inspected historical revisions. Its exact deployed contents
still need comparison before attributing that difference to runtime behavior.

Final CloudWatch retrieval contains 441 decoded status samples, ending at
10:45:58 CEST with 23,494 telemetry messages and 59,638 video frames. Telemetry
has stayed unchanged for 797.269 seconds; control was never held. Credential
generation 3 appears at 10:44:13 CEST, with video continuing and telemetry still
stalled. The initial-role expiration at 11:09:10 CEST was not crossed.

The operator terminated the fifth host at 10:46:02.014 CEST
(08:46:02.014 UTC). Read-only `GetMicrovm` and the complete image-filtered
inventory verify all five attempts `TERMINATED` and zero active runs. The local
cloud reader exited and its ingress token was removed. A final scan of 2,084
CloudWatch events, both native probe outputs and extracted board logs found no
credential values, access-key pattern, private key, signed query, ICE password
or exact ingress token. This is not direct inspection of managed snapshot
memory. Stack, images, packages and logs remain deliberately retained for
diagnosis and can incur storage charges.

The fifth observation has not passed final acceptance. Review the telemetry
failure before another cloud attempt or subsequent implementation. Board
logging/read-only-root restoration remains a manual operator step in the
[capture procedure](tbot-outage-capture.md#7-retrieve-evidence-after-restart-and-finish-the-maintenance-window).

Evidence: `tmp/issue-165/fifth-run-initial-evidence.json`,
`fifth-run-board-capture-confirmation.json`,
`fifth-run-initial-role-expiration-metadata.json`,
`fifth-run-reopening-evidence.json`,
`fifth-run-renewal-and-telemetry-stall-evidence.json`,
`fifth-run-telemetry-stalled-http-status.json`,
`fifth-run-telemetry-stalled-shadow.json`,
`fifth-run-board-kernel-1035-evidence.json`,
`fifth-run-board-live-1035-snapshot.log`,
`fifth-run-diagnostic-secret-scan.json`,
`fifth-run-board-archive-evidence.json`,
`fifth-run-board-deployment-baseline.json`,
`fifth-run-final-status-samples.json`, `fifth-run-cloudwatch-final.json`,
`fifth-run-final-diagnostic-secret-scan.json`,
`fifth-run-cleanup-evidence.json`, `fifth-run-terminated-runtime.json`,
`fifth-run-final-inventory.json`, `fifth-run-observation-progress.json` and
fifth-run incremental raw batches.
No production runtime or device code changed for this retry.

## Recovery correction after the fifth observation

The operator confirms that Office MAVLink telemetry continues to update. A fresh
native C++ observer at 10:52:47–10:54:17 CEST also receives both streams, with
last reported totals of 1,366 telemetry messages and 2,230 video frames, then
closes cleanly on SIGINT. This narrows the fifth-run failure to the old agent
peer; it does not establish board-wide telemetry loss.

The current runtime now retires a connected MAVLink peer after fifteen seconds
without a valid received telemetry frame. It uses per-peer receipt counters and
the existing asynchronous teardown/bounded retry, leaves healthy video intact,
releases authority and fences queued sends before retiring telemetry, and never
reacquires control automatically. Lifecycle success, control replies, malformed
frames and callbacks from retired peers do not postpone recovery.

Native macOS CTest passes both targets (5.44 seconds), and all fifteen Python
checks pass. A real AWS/board test deliberately suppresses telemetry receipt
inside its own observer while the SDK peer remains connected. The runtime emits
`no MAVLink telemetry for 15 seconds`, reopens telemetry and receives frames
again while the original video connection keeps flowing. Independent explicit
peer recovery, local lifecycle override and the fifteen-second authoritative
verification timeout also pass; no control is acquired. This validates native
behavior, not the corrected source inside a MicroVM.

New source-only BUILD_ID:
`c963a8c8a9df7d4b6760bb244de017056e430b36fa18f6f03f17dce0ed47636d`.
ZIP SHA-256:
`209bd78f25c2eb293b1dd6bbfe051436ee89ed7884f430aa5a84c50f28154287`.
All 32 packaged files match the current source. The existing stack/build role,
base image, hooks and networking are reused; no board installation or stack
update is needed. Local Linux container rebuilding was unavailable because this
session's Lima default instance could not be reached (host sysctl access denied
and forwarded SSH port refused). The operator started the AWS image at
11:10:49 CEST. Read-only retrieval of its S3 object matches the audited ZIP
SHA-256 exactly. AWS verified all 32 source hashes, passed both native ARM64
CTest targets in 2.90 seconds, emitted the AArch64 ELF header, completed the
final snapshot-safe OpenSSL linking checks and logged the pre-run waiting state
from both image hooks. Version `1.0` became SUCCESSFUL/ACTIVE at 11:18:25 CEST.
This supplies native Linux evidence for the corrected source without a local
Lima rebuild. The sixth run now confirms restored device/role/ingress startup
as recorded above. The later board outage interrupts long renewal acceptance;
operator cleanup is verified.

Preflight confirmed actual REDCON 1 with unexpired retained
board/MAVLink/video capabilities, the expected exact named-shadow role policy
and all five previous MicroVMs terminated. All 32 current source files matched
the new image input. The operator has since refreshed the foreground sampler
and executed `tmp/issue-165/operator-sixth-run.md`; do not launch again.
The reader requires growing telemetry/video for at least sixty seconds after
the externally recorded initial role expiration; an earlier generation change
or retained counter totals cannot satisfy that audit. No image or MicroVM has
been created by the agent. Preserve prior
packages and image evidence.

Evidence: `tmp/issue-165/fifth-run-telemetry-isolation-evidence.json`,
`silent-telemetry-native-tests.log`, `silent-telemetry-live-check.log`,
`silent-recovery-package-audit.json`, `silent-recovery-build-start-evidence.json`,
`silent-recovery-image-accepted-evidence.json`,
`silent-recovery-build-events.json`, `sixth-run-preflight-summary.json`,
`create-image-review-c963a8c8a9df.json` and the new immutable ZIP.

## Separate Office video closure during board credential renewal

The operator later reports “Board video ended by the device”, with MAVLink still
updating and one browser WebRTC connection gone. Board logs show both KVS
signaling sessions being recreated at 10:56:00 CEST (08:56:00 UTC). Read-only
CloudTrail metadata independently records successful board IoT-role issuance
at exactly 08:56:00 UTC, expiring 09:56:00 UTC. This is board-role evidence,
separate from the agent's execution role.

The board runtime recreates bridge-backed KVS sessions at their credential
refresh deadline, five minutes before expiration. Office's video/MCP data-channel
close handler ends the associated video peer and renders the quoted label;
the independently reconnecting MAVLink session can remain available. This timing
and source behavior explain a concrete recovery path to investigate for the
browser video failure; no browser-console event timestamp was captured. The
board boot ID and service PIDs stay unchanged, and native video reception works
after that recreation. Reopening the Office device page establishes a new viewer
without changing REDCON; the operator confirms that reloading restored both
video and telemetry. Office video recovery and the board Wi-Fi/MMC errors
remain separate findings; no Office or board behavior change is included in the
agent correction.

Evidence: `tmp/issue-165/board-office-video-renewal-metadata.json`,
`board-office-video-renewal-evidence.json` and its immutable board-log snapshot.

## Native preparation evidence — 2026-10-21

Starting committed revision: `1de1d3fc` (completed #164), with the current
uncommitted #165 source preserved in the package manifest.

- Native macOS `just agent::test` passes both CTest targets: the original ten
  runtime groups including real WebRTC peers, and the new MicroVM host checks.
  Fifteen Python tests pass: ten shadow contracts and five HTTP/WebSocket tests.
- The production executable serves `/ready` and `/validate` while both AWS
  configuration paths point to blocking FIFOs. This verifies the build phase
  does not read profiles. Local wire tests verify hook-port isolation, strict
  post-restore initialization, idempotent hooks, one attachment, fragmented
  text, binary telemetry/unauthorized-send rejection, message limits, and an
  oversized hook returning 413 without starting a runtime.
- A cached native build reuses all 646 objects unchanged. Linux ARM64 compilation
  of WebSockets, usrsctp and log4cplus passes in the second AWS image attempt;
  agent configuration failed on the install path described above.
- After the final CMake changes, native Mac checks again pass both CTest targets
  and all fifteen Python tests. The Lima image build passes both Linux CTest
  targets (2.74 seconds), verifies AArch64 and resolves OpenSSL to `/opt/snapsafe`.
  The final image is `linux/arm64`, runs as UID 10001 and contains no AWS
  credential environment variables. Its real entrypoint serves ready/validate
  as 200, rejects malformed run as 400 and wrong-port requests as 404, and keeps
  identity/credential/session state uninitialized throughout those checks.
  SIGTERM exits with code 0; the local test container was removed.
- AWS read-only `validate-template` passes. Image/run request inputs validate
  against botocore 1.43.116's `2025-09-09` service model. The operator submitted
  the image requests recorded above; the agent submitted no image/run request.
  CLI output-skeleton generation has invalid placeholder response
  fields; its failure was not treated as an input-validation result.
- Package inspection checks the exact zip/source allowlists, every source hash,
  the build identifier and trust bundle. macOS AppleDouble metadata is excluded.
- Read-only device inspection at 12:17 UTC reports `DDATA`, actual REDCON **1**
  with a successful target-1 command. Keep that state through cloud observation.

Evidence is under `tmp/issue-165/`: `final-tests.log`,
`final-host-wire-tests.log`, `cached-build-result.json`, `template-validation.json`,
`input-validation.txt`, `package-audit.json`, source/package records and read-only
inventories. These are preparation results, not live-cloud acceptance.

## Prepare locally

Use the native prerequisites/profile from [agent/README.md](../agent/README.md),
plus AWS CLI with `lambda-microvms`, `zip`, and `jq` for the operator commands.
Run from the repository root:

```sh
just agent::test
just agent::probe-package
```

The second recipe only prepares a local zip under `tmp/agent-probe-package/`.
It includes an explicit source allowlist, source SHA-256 manifest, committed
revision, dirty status, build identifier, Dockerfile and verified trust roots.
It excludes credentials, `.git`, caches, evidence and unrelated subprojects.
Preserve the printed package checksum. Changing source requires repackaging.
The build identifier is the source-manifest hash and appears in runtime status.
The prototype is not a published `agent` release and does not bypass #169.

## Build the container locally on an Apple Silicon Mac

An ARM64 Lima guest with `nerdctl.lima` is sufficient. The existing guest reports
`aarch64`, and its BuildKit builder accepts this image context. `nerdctl build`
requires a running BuildKit daemon; see the
[nerdctl build guide](https://github.com/containerd/nerdctl/blob/main/docs/build.md)
and [Lima container guide](https://lima-vm.io/docs/examples/containers/).
For this C++ build, four CPUs, eight GiB of VM memory and forty GiB of disk space
are suggested development allocations, not measured runtime requirements.

From the repository root, prepare the same source context and build it:

```sh
nerdctl.lima version
just agent::probe-package
nerdctl.lima build --platform linux/arm64 --progress=plain \
  --tag txing-agent-probe:local "$PWD/tmp/agent-probe-package"
```

This selects ARM64, shows full output and stores the image in the local Lima
containerd image store. The Dockerfile compiles the Linux application, runs CTest and verifies ARM64
and final library resolution. This build needs public network access to ECR,
AL2023 repositories and GitHub; it needs no AWS credentials. Keep Docker's build
cache for subsequent iterations. Docker Desktop is an optional alternative:
use `docker buildx build --platform linux/arm64 --progress=plain --load` with
the same tag and context. It is not required when Lima already works.

Local container success does not exercise AWS snapshot/restore hooks, execution
roles, managed ingress or real cloud KVS connectivity. Those remain the live
MicroVM acceptance gate. Local evidence is in
`tmp/issue-165/local-container-evidence.json`, `nerdctl-build-archives.log`,
`local-container-provenance.txt`, `local-container-http.json` and
`native-after-archive-staging.log`.

## Operator: create the disposable resources

The root [AGENTS.md](../AGENTS.md) prohibits the agent from executing AWS resource
mutations. The following commands are **manual operator actions**. Inspect the
template and Dockerfile first. The template creates only a private artifact
bucket, seven-day log group and generated-name build/execution roles. The
runtime role can read the selected Thing and its shadow data, and view its two
existing channels; it cannot create channels, write shadows or launch compute.
No VPC, NAT, ECR repository, controller or trigger is created.

Keep braces around `${AWS_REGION}` inside ARNs. In an interactive zsh session,
`$AWS_REGION:aws` applies a variable modifier and corrupts the ARN.

```sh
export AWS_PROFILE=mayor
export AWS_REGION=eu-central-1
probe_stack=txing-agent-probe-165
probe_thing=tbot-8yzfgj
probe_dir="$PWD/tmp/issue-165"
mkdir -p "$probe_dir"

aws cloudformation deploy --region "$AWS_REGION" \
  --stack-name "$probe_stack" --template-file agent/probe/stack.yaml \
  --parameter-overrides "ThingId=$probe_thing" --capabilities CAPABILITY_IAM

aws cloudformation describe-stacks --region "$AWS_REGION" \
  --stack-name "$probe_stack" > "$probe_dir/stack.json"
probe_bucket=$(jq -r '.Stacks[0].Outputs[] | select(.OutputKey=="ArtifactBucket") | .OutputValue' "$probe_dir/stack.json")
probe_build_role=$(jq -r '.Stacks[0].Outputs[] | select(.OutputKey=="BuildRoleArn") | .OutputValue' "$probe_dir/stack.json")
probe_execution_role=$(jq -r '.Stacks[0].Outputs[] | select(.OutputKey=="ExecutionRoleArn") | .OutputValue' "$probe_dir/stack.json")
probe_logs=$(jq -r '.Stacks[0].Outputs[] | select(.OutputKey=="LogGroup") | .OutputValue' "$probe_dir/stack.json")
probe_build_id=$(cat tmp/agent-probe-package/build-id.txt)
probe_image="$probe_stack-$(printf '%s' "$probe_build_id" | cut -c 1-12)"

aws s3 cp "tmp/agent-probe-package/$probe_build_id.zip" \
  "s3://$probe_bucket/probe/$probe_build_id.zip" --region "$AWS_REGION"

aws lambda-microvms create-microvm-image --region "$AWS_REGION" \
  --name "$probe_image" \
  --base-image-arn "arn:aws:lambda:${AWS_REGION}:aws:microvm-image:al2023-1" \
  --base-image-version 2 --build-role-arn "$probe_build_role" \
  --code-artifact "uri=s3://$probe_bucket/probe/$probe_build_id.zip" \
  --cpu-configurations '[{"architecture":"ARM_64"}]' \
  --resources '[{"minimumMemoryInMiB":4096}]' \
  --hooks file://agent/probe/hooks.json \
  --logging "cloudWatch={logGroup=$probe_logs}" \
  --tags '{"Issue":"165","Purpose":"disposable-feasibility"}' \
  --client-token "$probe_build_id" > "$probe_dir/image-created.json"
```

Confirm managed base version `2` is still `AVAILABLE` before creation. Read the
image ARN as shown below and inspect build progress. A successful image state
alone is insufficient: the chosen image version must be `SUCCESSFUL` and
`ACTIVE`. Preserve build logs proving ARM64 compilation, tests, source hashes,
and final snapshot-safe library resolution. Four GiB baseline provides build
headroom; this is not a runtime sizing/cost claim. Image builds, compute,
snapshots, logs, S3 and traffic can incur charges.

### Read the image ARN returned by AWS

`create-microvm-image` returns an `imageArn` field in its JSON response. The
creation command above saves that response to `tmp/issue-165/image-created.json`.
From the repository root, extract the field into the shell variable used by
the inspection and launch commands:

```sh
probe_image_arn=$(jq -er '.imageArn' tmp/issue-165/image-created.json)
printf '%s\n' "$probe_image_arn"
```

For the current successful build, this prints
`arn:aws:lambda:eu-central-1:453102798330:microvm-image:txing-agent-probe-165-5db8fe4d0334`.
This is the image ARN returned by AWS, including its account and source-derived
image name. The variable exists only in the current shell; repeat the extraction
when opening a new terminal. `jq -e` reports failure if the field is missing.

If the creation response file is missing, retrieve the ARN from AWS by the exact
image name. This read-only recovery command selects the current successful build;
use the corresponding source-derived name for a different build:

```sh
probe_image_arn=$(
  aws lambda-microvms list-microvm-images --profile mayor --region eu-central-1 \
    --output json |
    jq -er --arg name 'txing-agent-probe-165-5db8fe4d0334' \
      '.items[] | select(.name == $name) | .imageArn'
)
printf '%s\n' "$probe_image_arn"
```

There is no need to create another image to recover this value. Continue with
the build inspection using the assigned variable:

```sh
aws lambda-microvms list-managed-microvm-image-versions --region "$AWS_REGION" \
  --image-identifier "arn:aws:lambda:${AWS_REGION}:aws:microvm-image:al2023-1"

aws lambda-microvms get-microvm-image --region "$AWS_REGION" \
  --image-identifier "$probe_image_arn" > "$probe_dir/image.json"
aws lambda-microvms list-microvm-image-versions --region "$AWS_REGION" \
  --image-identifier "$probe_image_arn" > "$probe_dir/image-versions.json"
aws logs tail "$probe_logs" --region "$AWS_REGION" --since 1h
```

Use a new source-derived name after source changes; preserve the exact zip and
image/version associated with each attempt. Do not overwrite a recorded artifact.
If compilation or the hook contract fails, resolve that evidence within #165
before launching. Do not proceed to the production controller.

## Operator: launch and verify

Activate the existing registered TBot through its normal operator flow and keep
it at actual REDCON 1. Set the exact successful image version from the previous
response. The following launch uses only AWS-managed public connectors, passes
no secrets, and sets a fifty-minute (3000-second) hard lifetime. It deliberately omits the optional
idle policy. Inspect the returned configuration: if the service supplies an
idle-suspend policy, stop the experiment and resolve that contract; a long idle
timeout is not proof that automatic suspension is disabled.

```sh
probe_version='<successful ACTIVE image version>'
probe_run_token="$probe_build_id-$(date -u +%s)"
aws lambda-microvms run-microvm --region "$AWS_REGION" \
  --image-identifier "$probe_image_arn" --image-version "$probe_version" \
  --execution-role-arn "$probe_execution_role" \
  --ingress-network-connectors "arn:aws:lambda:${AWS_REGION}:aws:network-connector:aws-network-connector:ALL_INGRESS" \
  --egress-network-connectors "arn:aws:lambda:${AWS_REGION}:aws:network-connector:aws-network-connector:INTERNET_EGRESS" \
  --run-hook-payload "{\"thingId\":\"$probe_thing\",\"region\":\"$AWS_REGION\"}" \
  --maximum-duration-in-seconds 3000 \
  --logging "cloudWatch={logGroup=$probe_logs}" \
  --client-token "$probe_run_token" > "$probe_dir/run.json"

probe_id=$(jq -r .microvmId "$probe_dir/run.json")
probe_endpoint=$(jq -r .endpoint "$probe_dir/run.json")
probe_endpoint=${probe_endpoint%/}
aws lambda-microvms get-microvm --region "$AWS_REGION" \
  --microvm-identifier "$probe_id" > "$probe_dir/runtime.json"
```

Record `RUNNING`, image/version, execution role, both managed connectors,
`idlePolicy` absence and the actual endpoint readiness. The API state is
eventually consistent; use the endpoint to confirm application readiness.
CloudWatch `microvm status` lines must show the expected build/Thing/run IDs,
increasing telemetry/video counts, H.264 bytes with presentation/receipt clocks,
and both connections. SDK logs must identify the selected ICE candidate types
and whether a relay was selected. Allocating TURN credentials alone does not
prove relayed media was selected.

Generate an ingress token **only for 8081**. Keep it out of chat, diagnostics,
arguments, source, image configuration and the `/run` payload:

```sh
umask 077
aws lambda-microvms create-microvm-auth-token --region "$AWS_REGION" \
  --microvm-identifier "$probe_id" --expiration-in-minutes 30 \
  --allowed-ports '[{"port":8081}]' \
  --query 'authToken."X-aws-proxy-auth"' --output text > "$probe_dir/proxy-token"

# The C++ probe reads the token on stdin and never prints it.
tmp/agent-build/agent-microvm-probe "$probe_endpoint" \
  "$PWD/tmp/agent-trust/aws-roots.pem" 20 \
  < "$probe_dir/proxy-token" > "$probe_dir/attachment.log" 2>&1
```

The probe requests status, exchanges a text ping/pong, receives binary MAVLink
telemetry, and submits one validly framed binary message **without acquiring
control**. The runtime must reject that send through its existing Actions/Session
authority boundary. It reports H.264 metadata and counters, then detaches.
No MAVLink action should reach the board. Text commands in this minimal protocol
are `status`, `ping`, explicit `acquire` and `release`; binary messages contain
one complete MAVLink 2 frame. QGroundControl/discovery integration remains #166.

Also preserve an unauthenticated request returning 403 and an authenticated
request to forbidden hook port 8080 returning 403. Supply headers via stdin so
the token does not appear in process arguments:

```sh
curl --silent --show-error --output "$probe_dir/no-auth-body.txt" \
  --write-out '%{http_code}\n' --header 'X-aws-proxy-port: 8081' \
  "https://${probe_endpoint#https://}/status" > "$probe_dir/no-auth-status.txt"

{ printf 'X-aws-proxy-auth: '; cat "$probe_dir/proxy-token"; \
  printf '\nX-aws-proxy-port: 8080\n'; } | \
  curl --silent --show-error --header @- --output "$probe_dir/wrong-port-body.txt" \
    --write-out '%{http_code}\n' "https://${probe_endpoint#https://}/status" \
    > "$probe_dir/wrong-port-status.txt"
```

Leave a future runtime without human attachment for **more than fifteen minutes**,
within its **fifty-minute maximum**. Record consecutive UTC status samples with
increasing telemetry/video and `attached=false`, initial/reopened native probe
results, real selected ICE paths and absence of idle policy. End earlier on
lifecycle loss or another required stop condition. The board's renewal clock is
independent of VM start, so a full fifty-minute window is not guaranteed.

Record actual execution-role rotation when it occurs within the supported window:
a later credential generation, external role-assumption/finite-expiration metadata
and successful subsequent media/API activity. Increasing `providerCalls` alone
is insufficient. Never record tuples or fingerprints. The approved stage limit
supersedes the former requirement for a minute of media beyond original one-hour
STS expiration. Preserve a missing rotation as unproven; the duration decision
does not make a static tuple into refresh evidence. The existing seventh run
already supplies the required bounded renewal evidence and needs no repeat.

Capture logs and attachment results before termination. Treat KVS, snapshot,
credential, ingress and sustained-operation failures as evidence for review.
The documented board-renewal limitation is accepted only within this stage;
it does not authorize lifecycle bypass or another hosting architecture.

Ingress tokens and execution-role renewal are separate. Run initial/reopening
probes while a thirty-minute port-scoped token is valid; use read-only CloudWatch
capture for the remaining observation. A later endpoint inspection can require
another operator-issued 8081-only token. Token issuance remains an operator AWS
mutation. Do not exceed the fifty-minute hosting budget to wait for renewal.

## Operator: terminate and record cleanup

The experiment is incomplete until the operator terminates the actual MicroVM
and confirms its final state. The hard lifetime is a cost backstop, not cleanup
evidence. Preserve logs and non-secret provenance before removing resources.

```sh
aws lambda-microvms terminate-microvm --region "$AWS_REGION" \
  --microvm-identifier "$probe_id" > "$probe_dir/terminate.json"
aws lambda-microvms get-microvm --region "$AWS_REGION" \
  --microvm-identifier "$probe_id" > "$probe_dir/terminated-runtime.json"
aws lambda-microvms list-microvms --region "$AWS_REGION" \
  --image-identifier "$probe_image_arn" > "$probe_dir/final-inventory.json"
```

Wait for authoritative `TERMINATED` and confirm no pending, running or suspended
probe remains. Record operator/time and terminate-hook/session cleanup logs.
Then manually remove the disposable image (including retained versions), its S3
artifact and stack if no longer needed. Inspect actual IDs and contents first;
the artifact bucket must be empty before stack deletion. These removals are
operator actions, not an automatic cleanup script. Remove the local token file.
Logs/images/artifacts retained deliberately can continue to incur storage costs.

## Acceptance audit

| Requirement | Required authoritative evidence | Current state |
| --- | --- | --- |
| Same runtime built/executed as Linux ARM64 in Frankfurt | Image build/tests, ELF and actual restored identity matching immutable source | Passed: accepted corrected image `c963a8c8a9df` v1.0; ARM64 CTest 2/2; exact runtime source |
| Post-restore identity/credentials/sessions; clean snapshot boundary | Waiting build hooks, initialization after actual `/run` | Passed: waiting ready/validate hooks and distinct restored run identities; no direct claim to inspect AWS-encrypted snapshot memory |
| Real independent telemetry/video; ICE/TURN | Actual counters/metadata and selected candidate logs | Passed: independent MAVLink/H.264 and both selected relay-to-relay paths |
| Execution-role refresh without secret output | Real tuple change, external STS expiration metadata, subsequent traffic inside current-stage limit | Passed: generation 2 followed by 892.542 seconds, +15,423 telemetry/+26,604 video; secret scans zero; original-expiration test superseded by 2026-10-23 decision |
| Authenticated port-scoped manual traffic | Initial/reopened native probe and 200/403/403 ingress checks | Passed: probes 371/345 frames, H.264 metadata, pong and unauthorized-send rejection |
| More than fifteen minutes without attachment; idle disabled | Healthy sampled interval and actual no-idle launch configuration | Passed: 1910.438 seconds, 382 healthy unattached samples, both counters grow at every sample, control false |
| Operator termination and cleanup | Operator record, authoritative terminal state and complete current inventories | Passed: all seven terminations recorded; fresh inventories zero active; both seventh tokens removed; storage retained deliberately |
| Failure review and approved limitation | Recorded architecture/scope outcome, no silent fallback or automation | Passed: operator accepts fifty-minute ceiling and defers board renewal repair; later issues remain unimplemented |

Record exact commands, source/build hashes, dependency/base versions, image and
run IDs, device/region, UTC observation windows, counts, selected ICE/TURN path,
role refresh, ingress tests and cleanup in #165. Keep the issue open while any
required evidence is missing. No automatic commits, resource mutations or
physical control are authorized for the agent.
