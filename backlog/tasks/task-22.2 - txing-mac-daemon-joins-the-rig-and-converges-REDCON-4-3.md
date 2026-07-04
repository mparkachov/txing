---
id: TASK-22.2
title: txing-mac-daemon joins the rig and converges REDCON 4-3
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 07:45'
updated_date: '2026-07-04 17:03'
labels: []
milestone: m-1
dependencies: []
references:
  - rig/internal/protocol/protocol.go
  - rig/internal/ipc/ipc.go
  - rig/cmd/txing-thread-connectivity
  - rig/justfile
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 51000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create the txing-mac-daemon Go module with the rig IPC watch-layer role: it consumes rig inventory, publishes capability state and heartbeats for its thing, accepts REDCON commands 1-4 with pending/accepted/succeeded/failed results, and drives a redcon state machine whose power evidence lets the rig publish DBIRTH and converge REDCON 4 and 3. Includes just recipes (build/start/stop/restart/log/check/test), the daemon.env template, and wire-format tests pinned against the rig schema 2.0 payloads.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 With the rig and mac daemon running locally, the registered mac thing is born (DBIRTH) and office REDCON commands 3 and 4 converge with command feedback and correct DDATA redcon values.
- [x] #2 Stopping the mac daemon leads to DDEATH within the capability state TTL, and restarting it re-births the device without rig restarts.
- [x] #3 All REDCON targets 1-4 are accepted; targets above the currently achievable level converge to the highest level supported by published evidence.
- [x] #4 The daemon is operated only through just recipes with logs and PID files under the mac run directory, and go tests cover the state machine and IPC wire formats.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. New Go module devices/mac/daemon (stdlib only): internal/rigadapter carries a pinned verbatim copy of the rig schema-2.0 wire contract (rig/internal/protocol/protocol.go minus BLE/Thread normalizers) and the ipc.Client from rig/internal/ipc.
2. internal/macconfig: daemon.env loader with process-env-over-file precedence (rig convention), default config dir TXING_MAC_CONFIG_DIR or ~/.config/txing/mac-daemon, fields ThingID, IPC socket (darwin default /tmp/txing-rig), initial redcon, state/heartbeat intervals.
3. internal/macdaemon: redcon state machine (targets 1-4 all accepted; watch outputs power=target<4, transportRedcon=target; capabilities only sparkplug+power so no board-owned keys leak into IPC state) and an Adapter modeled on rig/internal/thread/runtime.go: inventory gating on own thing with thingType mac, retained CapabilityState on transitions + 30s republish, retained heartbeat 10s (adapterId dev.txing.mac.Daemon), command flow accepted->succeeded/failed with deadline and mismatch handling, IPC reconnect loop.
4. cmd/txing-mac-daemon: --config-dir/--dry-run/--version, signal handling, local stdout logging (CloudWatch arrives with the action layer task).
5. devices/mac/justfile (build/start/stop/restart/log/check/test, run dir /tmp/txing-mac, fixed dev version, nohup+pid like rig) + root justfile mod mac.
6. Tests: config parsing/precedence, wire-format goldens for state/heartbeat/command/result/inventory JSON, state machine table, adapter command/inventory flows via fake publisher. Validation: go test, just recipes, live ladder against the running local rig.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented: new Go module devices/mac/daemon (stdlib only).
- internal/rigadapter: pinned verbatim copy of the rig schema-2.0 wire contract (rig/internal/protocol) and the IPC client (rig/internal/ipc), with golden wire-format tests for state/command/result/heartbeat/inventory JSON and topic builders.
- internal/macconfig: daemon.env loader, process-env-over-file precedence, default dir TXING_MAC_CONFIG_DIR or ~/.config/txing/mac-daemon, darwin IPC socket default /tmp/txing-rig/rig-ipc.sock, TXING_MAC_INITIAL_REDCON (default 4), state/heartbeat intervals.
- internal/macdaemon: Machine (targets 1-4, no normalization), CapabilityStateFor (sparkplug always, power below 4, transportRedcon metric; never declares board/mcp/video), Adapter modeled on the thread adapter (inventory gating on own thing with thingType mac, birth-on-presence state publish, retained state + 30s republish, retained heartbeat 10s, accepted->succeeded/failed command flow with deadline handling, adapterId dev.txing.mac.Daemon), Run loop with IPC reconnect that preserves the REDCON machine across rig restarts.
- cmd/txing-mac-daemon: --config-dir/--dry-run/--version, local stdout logging (CloudWatch arrives with the action layer in 22.3).
- devices/mac/justfile (test/build/start/stop/restart/log/check, nohup+PID under /tmp/txing-mac, fixed 0.0.0-dev version) + root justfile mod mac; devices/mac/README.md run documentation.
Validation so far: go test/vet/gofmt clean including a real-Unix-socket session integration test (retained inventory birth, command round trip, clean shutdown; macOS sun_path length pitfall handled); just mac::check dry-run works; daemon retries dial cleanly while the rig socket is absent; shared/aws pytest 139 and office 168 unaffected.
Remaining for AC 1-3: live ladder against the local rig requires the mac thing to exist in AWS (user-run: just aws::deploy, just aws::deploy-device <local-rig-id> mac <name>), then office REDCON 3/4 commands and DDEATH-on-stop observation.

Live validation completed against the registered thing mac-rcg3rg under rig local-hz0ny3 (registration run by the user per the AWS gate):
- DBIRTH at REDCON 4 on daemon start; office ladder confirmed by the user: command 3 converged with feedback, command 2 was accepted and reported 3 (no board/mcp evidence yet), command 4 returned to Cold Camp. Daemon log shows the full DCMD->IPC command receipts (dcmd-mac-rcg3rg-5/6/7).
- Death drill: daemon stopped 16:59:30, office showed DDEATH within the 150s TTL, restart at 17:02:40 re-birthed at REDCON 4 without touching the rig (user-confirmed).
- Two fixes landed during validation: devices/mac/justfile now exports TXING_RIG_IPC_SOCKET (the exported TMPDIR broke the os.TempDir-based Go default; same pattern as rig/justfile), and the daemon logs the socket it dials so a wrong path is visible.
- Added rig/internal/manager/mac_device_test.go: the real manager convergence driven by the daemon's exact wire payloads (birth 4, DDATA 3, target-1 capped at 3, board+mcp=2, video=1, DDEATH on TTL). rig internal tests 9/9 ok, mac module 3/3 ok.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
txing-mac-daemon's watch layer is live: a stdlib-only Go module whose rig IPC adapter (adapterId dev.txing.mac.Daemon, pinned schema-2.0 wire copy with golden tests) births the mac thing under the local rig, accepts all REDCON targets 1-4 with accepted->succeeded/failed feedback, publishes sparkplug/power/transportRedcon evidence, survives rig restarts, and expires into DDEATH within the capability TTL when stopped. Validated live end-to-end with mac-rcg3rg: office ladder 4->3, above-evidence targets capped at 3, DDEATH/rebirth drill confirmed. Cross-module contract tests drive the real rig manager with the daemon's exact payloads including the future board-evidence path to REDCON 2/1. Operated via just mac::{start,stop,restart,log,check,test}.
<!-- SECTION:FINAL_SUMMARY:END -->
