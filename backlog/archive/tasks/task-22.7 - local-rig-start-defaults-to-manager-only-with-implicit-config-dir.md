---
id: TASK-22.7
title: local rig start defaults to manager-only with implicit config dir
status: Done
assignee:
  - '@claude'
created_date: '2026-07-04 15:56'
updated_date: '2026-07-04 16:01'
labels: []
milestone: m-1
dependencies: []
references:
  - rig/justfile
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
parent_task_id: TASK-22
priority: medium
ordinal: 56000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
just rig::start without arguments starts only txing-sparkplug-manager using the daemon's built-in config resolution (TXING_RIG_CONFIG_DIR or ~/.config/txing/rig-daemon, matching the raspi root-config convention). BLE and Thread connectivity daemons are opt-in for development runs. Documentation reflects the new defaults.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 just rig::start with no arguments brings the local rig edge node to NBIRTH redcon=1 with only the sparkplug manager process running and no BLE or Thread processes or log noise.
- [x] #2 BLE and Thread daemons can still be started explicitly for connectivity development, including the no-ble mode.
- [x] #3 Rig and mac documentation shows the argument-free start flow with the config bundle unpacked to the default config directory.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
rig/justfile start signature is now: start config_dir='' connectivity='none' no_ble='false'. Default starts only txing-sparkplug-manager; connectivity=all also starts the Thread and BLE daemons (BLE honors no_ble=true). Recipes were refactored around a start_daemon helper; restart mirrors the new arguments; log tails only existing log files and errors when none exist. No Go change was needed: rigconfig already resolves the config dir as TXING_RIG_CONFIG_DIR then ~/.config/txing/rig-daemon, which matches the raspi /root/.config convention. Docs updated: docs/components/rig.md (argument-free flow, opt-in connectivity, bundle unpacked to ~/.config/txing/rig-daemon), docs/development.md, devices/mac/README.md. test_versioning justfile assertions updated. Validation: shared/aws pytest 139 passed; just --list parses; connectivity argument validation exercised.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
just rig::start now defaults to the local rig shape: only the Sparkplug manager starts, and the config directory is resolved like raspi (TXING_RIG_CONFIG_DIR or ~/.config/txing/rig-daemon) instead of being a CLI argument. Thread and BLE connectivity daemons are opt-in via 'just rig::start "" all [true]'. Documentation shows the argument-free flow with the rig bundle unpacked into the default config directory.
<!-- SECTION:FINAL_SUMMARY:END -->
