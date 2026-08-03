---
id: doc-20
title: 'Milestone: multi-user device observation'
type: guide
created_date: '2026-06-17 07:09'
updated_date: '2026-06-17 07:10'
---
# Milestone: multi-user device observation

## Outcome

Office supports multiple simultaneous observers for every device type while preserving exactly one active MCP controller for MCP-capable devices. REDCON remains unchanged through Sparkplug.

## Scope

- Update device observation and control UI behavior in Office.
- Update MCP active-control status contracts and docs.
- Validate current KVS multi-viewer behavior for video-capable devices without adding a new media path.
- Keep implementation generic across device adapters.

## Exit criteria

- Two signed-in users can view the same AWS device from two browsers and see consistent state.
- Non-MCP device types remain multi-user view-only.
- MCP-capable devices allow only one active controller while other users observe.
- Explicit takeover switches MCP control and stops previous motion.
- Two browsers can view the same bot video while only one controls the bot.
- REDCON tests and behavior remain unchanged except for existing commandability rules.

## Validation

- Office tests cover observer/control UI state and unchanged REDCON behavior.
- Daemon tests cover two MCP sessions, rejected non-owner actuator calls, takeover, epoch switch, and stop-on-takeover.
- Manual validation follows the first-test and final-test scenarios from the architecture doc.

## Rollout notes

- Office changes roll out through the normal Cloudflare Pages Git deployment.
- Daemon/schema/doc changes require the normal release and manual board runtime update flow.
- No AWS infrastructure deployment is expected unless future implementation discovers an existing policy gap.

## GitHub issue references

- [#43 — Milestone: multi-user device observation](https://github.com/mparkachov/txing/issues/43) (migrated from `TASK-20`)
- [#44 — Office supports multi-user observation across device types](https://github.com/mparkachov/txing/issues/44) (migrated from `TASK-20.1`)
- [#45 — Office exposes single active MCP controller state](https://github.com/mparkachov/txing/issues/45) (migrated from `TASK-20.2`)
- [#46 — Daemon active-control behavior is covered for multiple MCP sessions](https://github.com/mparkachov/txing/issues/46) (migrated from `TASK-20.3`)
- [#47 — Video-capable devices support simultaneous viewers on the existing KVS path](https://github.com/mparkachov/txing/issues/47) (migrated from `TASK-20.4`)
