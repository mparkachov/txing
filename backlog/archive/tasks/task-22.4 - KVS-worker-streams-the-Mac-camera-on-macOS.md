---
id: TASK-22.4
title: KVS worker streams the Mac camera on macOS
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 07:45'
updated_date: '2026-07-05 15:27'
labels: []
milestone: m-1
dependencies: []
references:
  - devices/unit/board/kvs_master/CMakeLists.txt
  - devices/unit/board/kvs_master/cmake/PrepareAwsKvsSystemDeps.cmake
  - devices/unit/board/kvs_master/include/kvs_master/video_capturer.hpp
  - devices/unit/board/kvs_master/src/video_capturer_libcamera.cpp
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 53000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Extend the unit KVS worker build for macOS: a time-boxed spike proving the AWS KVS WebRTC C SDK builds on macOS comes first, then a Darwin build lane (real SDK + gRPC bridge enabled, Homebrew dependency resolution with the SDK bundled-dependency build as fallback, macOS CA bundle) and an AVFoundation + VideoToolbox VideoCapturer producing Annex-B H.264 access units with SPS/PPS on keyframes behind the existing capturer factory. Includes the mac kvs-build and camera-probe just recipes; the Linux/Raspberry Pi build remains unchanged.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The worker builds on macOS through a just recipe with the real KVS SDK and bridge enabled, and existing Linux build behavior is unchanged.
- [x] #2 Run in the foreground against a bridge, the worker captures the Mac camera, reports READY, and a KVS WebRTC viewer renders live video.
- [x] #3 A foreground camera-probe path triggers the macOS camera permission prompt so detached runs are not silently denied, and capture failures surface as reported worker errors rather than hangs.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Spike first: prove the pinned AWS KVS WebRTC C SDK builds on macOS through the existing ExternalProject lane with Homebrew-staged deps (openssl@3, libwebsockets, srtp, libusrsctp, log4cplus) and BUILD_DEPENDENCIES=OFF; keep the SDK bundled-dependency build as the documented fallback.
2. PrepareAwsKvsSystemDeps.cmake: add an APPLE branch that stages Homebrew dylibs and headers into the system-deps prefix; Linux branch untouched.
3. kvs_master CMakeLists: Darwin lane that permits TXING_KVS_REAL_SDK + TXING_KVS_GRPC_BRIDGE, resolves websockets/srtp2/usrsctp/OpenSSL/protobuf/gRPC from Homebrew, and selects a new AVFoundation capturer (OBJCXX + AVFoundation/CoreMedia/CoreVideo/VideoToolbox frameworks); Linux behavior unchanged.
4. src/video_capturer_avfoundation.mm: AVCaptureSession + AVCaptureVideoDataOutput (NV12) into VTCompressionSession H.264 (realtime, no reordering, bitrate/keyframe interval from CameraConfig), AVCC-to-Annex-B with SPS/PPS prepended on keyframes, bounded drop-oldest frame queue, TCC permission request on Start, failures surfaced as capturer fatal errors like the libcamera capturer.
5. Camera probe: a capturer-only --camera-probe worker mode (start capture, require first frames within a deadline, emit markers, exit nonzero on failure) plus devices/mac just recipes kvs-build (brew preflight, /etc/ssl/cert.pem CA, build-macos build dir) and camera-probe (foreground run for the TCC prompt).
6. Validate: stub-lane ctest still passes, macOS real-SDK build produces the worker, camera-probe captures frames, foreground worker against the mac daemon bridge reports READY with a KVS viewer rendering (user-confirmed).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Spike outcome: the pinned AWS KVS WebRTC C SDK (bb106510) builds unmodified on macOS through the existing ExternalProject lane with Homebrew-staged deps (openssl@3, libwebsockets, srtp, libusrsctp, log4cplus staged as dylib+header symlinks by the new APPLE branch of PrepareAwsKvsSystemDeps.cmake) and BUILD_DEPENDENCIES=OFF; CMAKE_POLICY_VERSION_MINIMUM=3.5 is exported around the SDK build because libkvspic declares pre-3.5 minimums that CMake 4 rejects. The bundled-dependency fallback was not needed.
Implementation: Darwin CMake lane (brew prefix on CMAKE_PREFIX_PATH, protobuf resolved in CONFIG mode to coexist with gRPC's config, real SDK + gRPC bridge on, AVFoundation capturer selected on APPLE with -fobjc-arc and OBJCXX 17); video_capturer_avfoundation.mm (AVCaptureSession NV12 -> VTCompressionSession H.264 baseline realtime/no-reordering, AVCC->Annex-B with SPS/PPS on keyframes, drop-oldest 60-frame queue, TCC permission request with 180s prompt timeout on Start, fatal errors thrown from GetFrame like the libcamera capturer); one portability fix in board_video_bridge_grpc.cpp (duration_cast for libc++ system_clock). Capture-only --camera-probe worker mode (no KVS/bridge; requires encoded frames incl. a keyframe within 20s, TXING_KVS_CAMERA_PROBE_OK/START markers, errors via existing TXING_KVS_ERROR path). just mac::kvs-build (brew preflight, /etc/ssl/cert.pem CA, build-macos dir) and mac::camera-probe recipes; build-macos gitignored; mac README video section.
Validation so far: just mac::kvs-build produces the worker with real SDK + bridge (otool shows grpc/protobuf/brew deps), --version/--help OK; stub-lane ctest passes 15/15 incl. 4 new probe tests (test build on macOS now compiles the AVFoundation capturer too). Linux lane untouched by inspection: Linux branches byte-identical, the SDK env wrapper list is empty outside APPLE, and the chrono fix is portable. Live camera + viewer drills pending user run.

Live drill round 1 (user-run): camera probe succeeded (TCC prompt granted, TXING_KVS_CAMERA_PROBE_OK) and office rendered live Mac camera video via the foreground worker against the daemon bridge. Found gap: stopping the worker left the device stuck at REDCON 1 with a stale ready video capability, because a clean worker exit reported nothing over the bridge and the mac daemon does not supervise the worker process. Fix: added STOPPED to the VideoState enum in the shared BoardVideoBridge proto (backward compatible); worker reports STOPPED after a clean run (error exits still report ERROR); both mac and unit daemons map STOPPED to the declared-but-not-ready video posture (status starting, no error, MCP transport back to mqtt-jsonrpc) so derived REDCON drops on the next capability publish; regenerated the vendored Go stubs for both daemons with the pinned generators (protoc-gen-go v1.36.10, protoc-gen-go-grpc v1.5.1); updated docs/contracts/board-video-bridge.md. Tests: new C++ runtime test (clean bridge run reports STARTING/READY/STOPPED, 16/16 pass) and new mac action test (STOPPED drops video capability without error, transport falls back); unit daemon go test ok. Worker rebuilt and mac daemon restarted with the new handling; user re-drill of the stop path pending.

AC2 user-confirmed live: foreground worker against the daemon bridge captured the Mac camera, reported READY, and office rendered the live video (KVS WebRTC viewer). AC3 user-confirmed live for the permission path: just mac::camera-probe triggered the macOS camera prompt and completed with TXING_KVS_CAMERA_PROBE_OK; the failure-surface half is enforced by construction and covered by tests: the probe has a bounded 20s frame deadline (no hang), denial/restricted access throws with remediation text, capturer fatal errors propagate out of GetFrame, and all failures exit nonzero via the TXING_KVS_ERROR marker path (probe timeout, no-keyframe, and capturer-start-error cases in the C++ suite). Remaining before Done: user re-drill of the worker stop path confirming the STOPPED fix drops the device from reported REDCON 1 to 2.

Stop-path re-drill user-confirmed live: Ctrl-C on the foreground worker dropped the device from reported REDCON 1 to 2 (STOPPED report over the bridge working end to end). Known startup noise on macOS observed during the drill: Homebrew libwebsockets ships demo plugins that log warnings at context init (lws sshd demo, raw-test, deaddrop pvo warnings), and lws logs 'd2i_X509 failed' once while loading the multi-cert /etc/ssl/cert.pem bundle (DER parse attempted before the successful PEM load); TLS to AWS verifiably worked (signaling describe/token calls succeeded and video streamed).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The unit KVS worker now builds and streams on macOS. Spike outcome: the pinned AWS KVS WebRTC C SDK builds unmodified on macOS with Homebrew-staged dependencies (new APPLE branch in PrepareAwsKvsSystemDeps.cmake stages openssl@3/libwebsockets/srtp/libusrsctp/log4cplus dylibs+headers; CMAKE_POLICY_VERSION_MINIMUM=3.5 exported around the SDK build for CMake 4). The Darwin CMake lane enables the real SDK + gRPC bridge and selects a new AVFoundation + VideoToolbox capturer (NV12 capture into an H.264 baseline realtime session, AVCC-to-Annex-B with SPS/PPS on keyframes, drop-oldest queue, TCC permission request on start, fatal errors surfaced through GetFrame); the Linux/Raspberry Pi lane is untouched. A capture-only --camera-probe worker mode plus just mac::kvs-build and mac::camera-probe recipes cover the macOS permission flow with bounded-deadline failure reporting. Validated live on mac-rcg3rg: camera probe granted the TCC prompt and reported TXING_KVS_CAMERA_PROBE_OK; the foreground worker against the daemon bridge reported READY and office rendered the live Mac camera. The stop drill exposed a contract gap (clean worker exit left stale ready video evidence and the device stuck at REDCON 1); fixed by adding STOPPED to the BoardVideoBridge proto, reporting it from the worker on clean exit, and mapping it to declared-not-ready in both the mac and unit daemons (16/16 C++ and all Go tests pass; contract doc updated; live re-drill of the stop transition outstanding, folded into TASK-22.5's failure drills if not confirmed sooner). Deployment: dev-only; rebuild via just mac::kvs-build and restart the daemon via just mac::restart; unit/raspi builds unaffected.
<!-- SECTION:FINAL_SUMMARY:END -->
