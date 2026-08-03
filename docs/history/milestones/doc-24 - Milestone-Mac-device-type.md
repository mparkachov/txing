---
id: doc-24
title: 'Milestone: Mac device type'
type: specification
created_date: '2026-07-03 07:44'
updated_date: '2026-07-03 07:46'
tags:
  - mac
  - device-type
  - milestone
---
# Milestone: Mac device type

## Goal

Introduce `mac` as a first-class txing device type that turns the development Mac into a managed end device for local e2e testing: registered in AWS IoT, born as a Sparkplug device under the locally running rig, commandable through all REDCON levels 4-1, and streaming the Mac camera over AWS KVS WebRTC at REDCON 1 for the office viewer.

## Scope

This milestone covers the device catalog/UI contract (manifest, shadow schemas, AWS type catalog, certificate bundle, office adapter), the `txing-mac-daemon` Go runtime playing both the rig IPC watch-layer role and the board-style action-layer role with a read-only MCP stub, the macOS build lane and AVFoundation/VideoToolbox capturer for the existing KVS worker, `just` recipes for dev operation, and the manual registration/operation runbook.

This milestone does not cover actuator MCP tools or the future command-line control surface, systemd units or release packaging for the mac client, changes to rig/witness/office video internals, or consolidation of shared daemon code into `devices/common/`.

The daemon lands in two reviewable slices: watch layer first (REDCON 4-3 through the rig), then the action layer (REDCON 2 with board and MCP stub); video work proceeds in parallel and converges in the final e2e task.

## Implementation tasks

- `TASK-22.1` - mac catalog and UI contract is first-class
- `TASK-22.2` - txing-mac-daemon joins the rig and converges REDCON 4-3
- `TASK-22.3` - mac daemon action layer reaches REDCON 2 with board and MCP stub
- `TASK-22.4` - KVS worker streams the Mac camera on macOS
- `TASK-22.5` - mac device reaches REDCON 1 with office-visible video

## Acceptance summary

The milestone is complete when a mac device can be registered through the documented runbook, is born under the local rig, converges through the full REDCON ladder from office with correct command feedback and lifecycle projections (DBIRTH/DDATA/DDEATH), answers read-only MCP tools at REDCON 2, streams live Mac camera video visible in the office video route at REDCON 1, survives the documented failure drills, and is validated by automated tests plus the documented manual e2e evidence. Existing device types remain unchanged.

## Required references

- Architecture spec: `backlog/docs/architecture/mac-device-type/doc-23 - Mac-device-type-architecture.md`
- Parent milestone task: `TASK-22`
- Lifecycle contract: `docs/sparkplug-lifecycle.md`
- Rig IPC contract: `rig/internal/protocol/protocol.go`
- Unit daemon contracts: `devices/unit/daemon`, `devices/unit/docs/board-video.md`, `docs/contracts/board-video-bridge.md`
- KVS worker: `devices/unit/board/kvs_master`
