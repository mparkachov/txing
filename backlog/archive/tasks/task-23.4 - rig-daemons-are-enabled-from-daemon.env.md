---
id: TASK-23.4
title: rig daemons are enabled from daemon.env
status: Done
assignee:
  - '@codex'
created_date: '2026-07-06 07:19'
updated_date: '2026-07-06 10:10'
labels: []
milestone: m-2
dependencies: []
references:
  - rig/rig-daemon.env.template
  - rig/justfile
  - rig/internal/rigconfig/config.go
  - docs/components/rig.md
documentation:
  - >-
    backlog/docs/architecture/rig-idle-cost-parity/doc-25 -
    Rig-REDCON-1-idle-cost-parity-architecture.md
  - >-
    backlog/docs/milestones/rig-idle-cost-parity/doc-26 -
    Milestone-rig-idle-cost-parity.md
parent_task_id: TASK-23
priority: medium
ordinal: 64000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Rig daemon enablement is explicit, readable, and configured from daemon.env for raspi and local rigs. Operators can keep the default manager-only posture, then enable BLE and/or Thread by editing config and restarting instead of changing service shape or relying on ambiguous flags. BLE no-radio/development behavior remains distinct from whether the BLE connectivity daemon is enabled.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The rendered daemon.env template defaults to sparkplug manager enabled and BLE and Thread connectivity disabled, with clear variable names for each daemon's enablement.
- [x] #2 The rig start/runtime path honors daemon.env enablement consistently for local and raspi-style rigs, so enabling BLE or Thread requires a config edit plus restart, not a different local-only command shape.
- [x] #3 BLE no-radio/development mode is named and documented separately from BLE daemon enablement, and existing behavior is either preserved or given an explicit migration path.
- [x] #4 Rig documentation explains the manager-only default, how to enable BLE and Thread, and how to verify which daemons are expected to run on macOS and raspi rigs.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect current rig daemon start/install paths for raspi and local, including daemon.env sourcing, systemd units, and local just recipes.
2. Add explicit daemon enablement variables with readable names and manager-only defaults in rig-daemon.env.template and config loading.
3. Update raspi systemd/runtime documentation and local start/check paths to honor the same daemon.env enablement rules for Sparkplug manager, BLE connectivity, and Thread connectivity.
4. Rename BLE no-radio development behavior separately from BLE daemon enablement, and document the required migration from TXING_BLE_NO_BLE to TXING_BLE_NO_RADIO without runtime backward compatibility.
5. Add focused tests for daemon.env defaults, env parsing, local recipe policy, and generated certificate/template policy where existing test seams allow it.
6. Update rig docs with manager-only default, enablement instructions for macOS and raspi, verification steps, and rollout notes.
7. Run rig validation and update TASK-23.4 evidence before closure.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented explicit rig daemon enablement from daemon.env with manager-only defaults: TXING_SPARKPLUG_MANAGER_ENABLED=true, TXING_BLE_CONNECTIVITY_ENABLED=false, TXING_THREAD_CONNECTIVITY_ENABLED=false. Local just start/check now source daemon.env and start or validate only enabled daemons; BLE/Thread cannot be enabled when the manager is disabled. Raspi systemd documentation uses daemon.env-backed ExecCondition gates for each service, with rig-daemon.target wanting all services while disabled services are skipped cleanly.

Renamed BLE development mode from the ambiguous no-BLE wording to TXING_BLE_NO_RADIO / --no-radio. Per user instruction, no runtime backward compatibility is implemented for old config fields; docs record the required rename from TXING_BLE_NO_BLE to TXING_BLE_NO_RADIO.

Validation: go test ./... in rig; python -m unittest shared.aws.python.tests.test_versioning shared.aws.python.tests.test_template_policy; just --justfile rig/justfile --list; just --justfile rig/justfile check with temporary default config (manager only); just --justfile rig/justfile check with temporary BLE+Thread+no-radio config (all three dry-runs); invalid temporary config with manager disabled and BLE enabled fails with exit code 2; git diff --check.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-23.4 completed. daemon.env now owns rig daemon enablement with manager-only template defaults, local just recipes and raspi service docs honor the same flags, BLE no-radio is separate from daemon enablement, and the old TXING_BLE_NO_BLE config name has a documented rename path without runtime compatibility.
<!-- SECTION:FINAL_SUMMARY:END -->
