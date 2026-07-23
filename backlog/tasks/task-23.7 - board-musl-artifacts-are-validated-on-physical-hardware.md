---
id: TASK-23.7
title: board musl artifacts are validated on physical hardware
status: Done
assignee: []
created_date: '2026-07-21 09:01'
updated_date: '2026-07-23 21:24'
labels: []
milestone: m-4
dependencies:
  - TASK-23.5
  - TASK-23.6
references:
  - docs/components/board.md
  - docs/components/cyberbrick-board.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 63000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Operator-run validation closing the milestone, mirroring TASK-22.6's role for m-3: the migrated artifacts are exercised on real boards. Agents prepare commands and evidence templates; the operator executes all on-device steps.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The static unit daemon and hardware worker from an Alpine-built unit release run on a physical Debian (Raspberry Pi OS) board with normal daemon operation, and the pinned last Debian-built KVS master still functions there.
- [x] #2 The full board stack including the musl-dynamic KVS master runs on a physical Alpine board installed from the documented runbook, with read-only root and OpenRC autostart unaffected.
- [x] #3 Evidence for both boards is recorded in the task's implementation notes.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
AC1 evidence - physical Debian board (Raspberry Pi Zero 2 W 'txing', Raspberry Pi OS trixie, kernel 6.18.33+rpt-rpi-v8, aarch64), operator-run 2026-07-22:

Baseline: all three unit tools at 0.14.14 (last Debian-built release); mise conf.d config with version_prefix unit-v; board healthy with viewer connected.

Detour found and fixed during validation: (1) first upgrade pulled unit-v0.15.4, which was Debian-built because the cyberbrick branch with the Alpine migration had never been pushed - the dispatched workflow ran the old Debian pipeline from the remote; hardware worker ldd showed glibc/grpc/protobuf dynamic linkage. (2) After pushing, the Alpine build job failed: JavaScript actions (checkout/upload-artifact) cannot run inside musl containers on arm64 runners. Fixed in both release-unit.yml and release-cyberbrick.yml by running the build job on the host and driving the pinned alpine:3.23.5 container via docker exec heredocs with workspace/temp mounted at identical paths; step bodies and container-side gates unchanged; test_versioning.py 21 passed + 8 subtests without test edits. This also means the cyberbrick release workflow had never run successfully before this fix.

Upgrade (writable-root window): mise upgrade of the static pair to Alpine-built unit-v0.15.6. Post-upgrade checks: txing-unit-daemon 0.15.6 ldd 'not a dynamic executable'; txing-unit-hardware-worker 0.15.6 ldd 'statically linked' (static-pie); txing-unit-kvs-master pinned at 0.14.14, ldd resolves libcamera.so.0.7 and libcamera-base.so.0.7.

Post-reboot: root filesystem ro; txing-unit.target and all three services active in the fresh boot; daemon logs version 0.15.6; frozen KVS master 0.14.14 streaming - TXING_VIEWER_CONNECTED and TXING_MCP_DATACHANNEL_OPEN within ~8s of service start. Note: hardware worker systemd start time displays as May 23 due to Pi no-RTC clock skew at early boot (before chrony sync); the current-boot journal logs version 0.15.6 for it, proving the new static binary is the running one.

Milestone finding during AC2 prep: fresh Alpine install came up on 3.24.1, and the operator decided the stack should target current Alpine instead of pinning back to v3.23. Coordinated Alpine bump 3.23.5 -> 3.24.1 applied across both release workflows (image, release check, publish notes, toolchain cache key), both daemon justfiles, assert-board-musl.sh, smoke-board-cross-distro.sh, build-board-static-toolchain.sh (grpc 1.76.0 -> 1.78.1 to match v3.24 apk; absl/protobuf/re2/c-ares apk versions unchanged), docs (cyberbrick-board.md, artifacts.md, installation.md), and test_versioning.py pins. Alpine v3.24 ships libcamera 0.7.1, so the Alpine soname is now libcamera.so.0.7 - identical to Debian trixie's; linkage checks distinguish ABIs by ELF interpreter, not soname, and 0.6-vs-0.7 test guards were flipped to guard against stale 0.6 references. Runbook gaps fixed: community apk repo must be enabled (libcamera/grpc/re2 live there); hostname requirement relaxed (thing id lives in daemon config). cyberbrick-v0.15.4 (first-ever cyberbrick release, built on 3.23.5) is incompatible with the 3.24.1 board (libcamera 0.6 linkage); cyberbrick bumped to 0.15.5 for the first 3.24.1-built release. Versioning tests: 143 passed after the change.

AC2 prep blocker: on the physical Alpine board, mise 2026.7.12 refused to resolve txing-cyberbrick-*@latest right after publishing cyberbrick-v0.15.5, warning 'no versions found ... matching date filter'. Cause: mise's minimum_release_age setting (default 24h; env MISE_MINIMUM_RELEASE_AGE) is a supply-chain guard that hides releases younger than the window, so a fuzzy 'latest' request resolves to nothing minutes after publish. Fix: set minimum_release_age = "0s" in the [settings] block of the board mise config; boards install first-party releases immediately by design. Applied to all four mise config surfaces in-repo (docs/components/cyberbrick-board.md, board.md, rig.md, rig/install-mise-tools.sh) plus test_versioning.py pins; 143 versioning tests pass. Note: MISE_MIN_RELEASE_AGE (tried first) is not a real setting name; the correct env var is MISE_MINIMUM_RELEASE_AGE.

AC2 real defect found on physical Alpine board and fixed: the musl-dynamic KVS master could not establish TLS to the AWS signaling endpoint on Alpine (X509_V_ERR=20 'unable to get local issuer certificate' at depth=2), so describeChannel/signaling never connected. Root cause: the cyberbrick build points the KVS SDK's TLS at Alpine's full /etc/ssl/certs/ca-certificates.crt (140 certs), but the SDK's TLS layer follows the server-presented chain and needs the single Starfield Services Root CA G2 anchor that AWS chains to; the full bundle fails where a one-cert anchor file succeeds (proven on-box: openssl s_client verifies with the bundle via trusted-first, but the KVS binary does not; extracting just Starfield Services Root CA G2 to a one-cert file and pointing the binary there made signaling connect through GetToken->Describe->GetEndpoint->GetIceConfig->Connect cleanly). This is the same anchor the Debian unit build already uses (its compiled default is the single Starfield G2 file). Fix: (1) kvs_session_real.cpp ResolveSignalingCaCertPath() now honors a runtime TXING_KVS_SYSTEM_CA_CERT_PATH env override (was compile-baked only); (2) runbook provisions /etc/txing/kvs-ca.pem by extracting Starfield Services Root CA G2 from the OS bundle and the KVS OpenRC init script exports TXING_KVS_SYSTEM_CA_CERT_PATH to it; (3) added 'openssl' CLI to runbook step 2; (4) OS/ABI contract documents the single-anchor requirement; (5) test_versioning guards the env override in code + the runbook steps. cyberbrick bumped 0.15.5->0.15.6 for the release carrying the env override. Note: cross-distro smoke passed on 0.15.5 because it only checks linkage/--version, never a live AWS TLS handshake (no creds in CI) - this class of bug is invisible to smoke. Linkage gate itself passed on 0.15.5: static daemon+worker, KVS master resolving libcamera.so.0.7 + full webrtc stack after the full step-2 package install.

CA fix design revised (operator feedback): instead of extracting the anchor into /etc/txing on the board, the Starfield Services Root CA G2 (SFSRootCAG2.pem) is now fetched from AWS's public repository by just aws::cert and shipped in the daemon config bundle alongside AmazonRootCA1.pem, landing in .config/txing/cyberbrick-daemon/ - reusing the existing cert-provisioning mechanism. shared/aws/scripts/aws_lib.sh: txing_cert_create_iot_bundle curls SFSRootCAG2.pem (chmod 644); txing_cert_write_runtime_tarball includes it (shared by rig + device daemon bundles; rigs ignore it, harmless). KVS OpenRC init script points TXING_KVS_SYSTEM_CA_CERT_PATH at /root/.config/txing/cyberbrick-daemon/SFSRootCAG2.pem. Removed the on-board openssl extraction step and the openssl CLI package addition. Note: AmazonRootCA1.pem (already in that dir) was tested and does NOT work - AWS presents Amazon Root CA 1 cross-signed by Starfield G2 and the SDK needs the Starfield issuer, so the new SFSRootCAG2.pem is required, not a reuse of the existing root. Code env override (0.15.6) unchanged. Tests: 143 pass; test_template_policy asserts the SFSRootCAG2 download.

AC2 on-hardware status after CA fix deployed (board on cyberbrick-v0.15.7): (1) CA/TLS fix VALIDATED end-to-end on the real release binary - after provisioning .config/txing/cyberbrick-daemon/SFSRootCAG2.pem, the KVS master completes the full AWS signaling handshake (GetToken->Describe->GetEndpoint->GetIceConfig->Connect) with zero SSL errors; proves both the TXING_KVS_SYSTEM_CA_CERT_PATH env override and the bundle-provisioned anchor work in production. (2) KVS master then exits on 'configured camera index is not available' and supervise-daemon retires it to failed - EXPECTED, no camera attached this phase; live video/viewer confirmation deferred to a camera-attached session. (3) Empty local daemon log is NOT a defect: the Go daemon logs to CloudWatch (imports aws-sdk cloudwatchlogs; main.go only stderr on fatal; RunRuntime has no stdout logging), so /var/log/txing-cyberbrick-daemon.log is empty by design - daemon health shown by stable non-respawning PID + bound board-video-bridge.sock. Fixed the runbook 'Expected' wording (was 'daemon log includes version=', implying the local log) to point to CloudWatch and document the camera/PWM expected states. (4) daemon + hardware worker autostart and stay up under OpenRC. Remaining for AC2: PWM overlay (step 6), read-only root (step 7), reboot-autostart check (step 8).

AC2 read-only-root reboot check PASSED (physical Alpine 3.24.1 Pi Zero 2 W, cyberbrick-v0.15.7): after a cold reboot, / and /boot both mounted ro; /etc/resolv.conf -> /run/resolv.conf with DNS resolving; /sys/class/pwm/pwmchip0 present (PWM overlay active) and the hardware worker log is clean (started version=0.15.7, no PWM errors); daemon + hardware worker autostart under OpenRC and stay up (stable non-respawning PIDs) with no source checkout and no GitHub access; KVS master autostarts and completes AWS signaling, then cycles on the absent camera as expected. Full musl stack validated under read-only root with OpenRC autostart. Only live camera streaming is unproven (no camera this phase) - deferred to a camera-attached session.

Runbook disk-layout fix (divergence found on hardware): the board's Alpine 3.24 'setup-disk -m sys' produces a UUID-based /etc/fstab with the boot FAT at /boot, NOT the /media/mmcblk0p1 + /dev/mmcblk0pN scheme the runbook assumed (that mount only exists during the diskless boot). The old fstab/aliases would have failed or risked an unbootable board. Fixed cyberbrick-board.md: §1 notes the post-sys-install /boot+UUID layout; §6 PWM overlay targets /boot/config.txt|usercfg.txt with an include check; §7 fstab is UUID-based (/ and /boot -> ro) with root-rw/root-ro aliases using /boot. Confirmed working on hardware (the reboot check above ran on this fixed layout). 143 versioning tests pass.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Both boards validated on physical hardware, closing milestone m-4. AC1 (Debian Pi Zero 2 W): the static unit daemon + hardware worker from an Alpine-built release run with normal operation and the pinned last Debian-built KVS master (0.14.14) still streams. AC2 (Alpine 3.24.1 Pi Zero 2 W): the full musl stack - static daemon + static hardware worker + musl-dynamic KVS master - installs from the documented runbook and runs under read-only root with OpenRC autostart surviving a cold reboot; the KVS master resolves libcamera 0.7 + the full webrtc stack and completes the AWS signaling handshake. Live camera video is the only deferred item (no camera attached this phase) and is documented as a later hardware confirmation. AC3: full evidence for both boards in the implementation notes. Fixes landed during validation: musl/arm64 release-workflow rewrite (host runner + docker exec); coordinated Alpine 3.23.5->3.24.1 retarget (incl. grpc 1.78.1, libcamera 0.7); toolchain cache; mise minimum_release_age=0s; KVS signaling CA fix (SFSRootCAG2.pem anchor provisioned via the daemon config bundle + TXING_KVS_SYSTEM_CA_CERT_PATH runtime override); and runbook corrections (community apk repo, /boot+UUID disk layout, CloudWatch daemon logging). Pending operator follow-up outside this task: commit+push the uncommitted repo changes, and confirm live camera streaming when a camera is attached.
<!-- SECTION:FINAL_SUMMARY:END -->
