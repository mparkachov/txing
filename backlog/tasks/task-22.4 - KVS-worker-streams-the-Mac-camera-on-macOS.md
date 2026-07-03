---
id: TASK-22.4
title: KVS worker streams the Mac camera on macOS
status: To Do
assignee: []
created_date: '2026-07-03 07:45'
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
- [ ] #1 The worker builds on macOS through a just recipe with the real KVS SDK and bridge enabled, and existing Linux build behavior is unchanged.
- [ ] #2 Run in the foreground against a bridge, the worker captures the Mac camera, reports READY, and a KVS WebRTC viewer renders live video.
- [ ] #3 A foreground camera-probe path triggers the macOS camera permission prompt so detached runs are not silently denied, and capture failures surface as reported worker errors rather than hangs.
<!-- AC:END -->
