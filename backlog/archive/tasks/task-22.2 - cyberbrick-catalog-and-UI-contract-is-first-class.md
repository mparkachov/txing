---
id: TASK-22.2
title: cyberbrick catalog and UI contract is first-class
status: Done
assignee:
  - '@codex'
created_date: '2026-07-15 07:36'
updated_date: '2026-07-15 20:22'
labels: []
milestone: m-3
dependencies: []
references:
  - devices/unit/manifest.toml
  - shared/aws/template.yaml
  - shared/aws/python/src/aws/type_catalog.py
  - shared/aws/scripts/aws_lib.sh
  - office/src/device-registry.ts
documentation:
  - >-
    backlog/docs/architecture/cyberbrick-device-type/doc-27 -
    Cyberbrick-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 51000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Register cyberbrick as a first-class txing device type across the device manifest, shadow schemas/defaults, AWS type catalog (CloudFormation + python catalog generation + tests), certificate bundle generation, and the office UI, without changing existing device types. Unit parity: full capability set including ble, REDCON 4-1 with unit's rules, board video channel resource, unit-equivalent office panel behavior.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The cyberbrick device type declares sparkplug/ble/power/board/mcp/video capabilities, REDCON command levels 4-1 with unit-shaped rules, per-capability shadow schema/default files, a web adapter, and the board video channel resource.
- [x] #2 AWS catalog deployment material and the python type catalog include cyberbrick with identical capability data, and shared AWS tests plus new cyberbrick coverage pass.
- [x] #3 Certificate bundle generation for a cyberbrick thing produces a cyberbrick-daemon config bundle including KVS master permissions on the device video channel.
- [x] #4 Office shows a registered cyberbrick device with unit-equivalent panel behavior (teleop, video at REDCON 1), covered by adapter and registry tests.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add the cyberbrick device-contract skeleton under devices/cyberbrick: a unit-parity manifest, copied per-capability shadow schemas/defaults with cyberbrick identity where payloads encode a device ID, the cyberbrick daemon environment template needed by certificate packaging, and a cyberbrick-owned web adapter/panel model with unit-equivalent REDCON, telemetry, drive, and video behavior.
2. Register cyberbrick in both AWS catalog sources: add CyberbrickTypeCatalogV2 to shared/aws/template.yaml and include cyberbrick manifest discovery in build_type_records, with focused device-catalog, type-catalog, and template-policy coverage proving CloudFormation/Python parity.
3. Extend certificate generation and the shared AWS cert recipe with the cyberbrick daemon template and deviceType:cyberbrick dispatch, then add non-mutating tests proving cyberbrick-daemon bundle metadata, rendered config identity, and KVS ConnectAsMaster permission scoped to the device board-video channel.
4. Register the cyberbrick adapter in office and add adapter/registry tests for unit-equivalent teleoperation, REDCON 1 video, telemetry, auto-open/close, and rendered controls.
5. Run the relevant shared AWS Python/shell validation and complete office test/build checks, inspect the final diff for unchanged existing device contracts, record results in TASK-22.2, and mark it Done only after all four acceptance criteria are evidenced. No AWS deployment or certificate creation commands will be run.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementation completed across the planned contract surfaces:

- Added devices/cyberbrick manifest with unit-parity capabilities, REDCON 4-1 rules, six shadow schema/default pairs, board-video resource, cyberbrick daemon env template, and a cyberbrick-owned office adapter/panel/model.
- Added CyberbrickTypeCatalogV2 to shared/aws/template.yaml and cyberbrick manifest loading to the Python type catalog. New tests cover manifest validity, catalog records/SSM leaves, CloudFormation parity, and unchanged unit-shaped capability data.
- Extended the shared cert recipe and POSIX shell dispatch with the cyberbrick daemon template and cyberbrick-daemon bundle type. Tests execute the dispatch with stubs and assert the shared KVS ConnectAsMaster policy remains scoped to the thing's board-video channel.
- Registered the adapter in office and added registry/adapter coverage for telemetry, REDCON teleoperation, REDCON 1 video, auto-open/close, active-control affordance, and Cyberbrick branding.

Validation so far:
- Shared AWS Python suite: 142 passed.
- Office suite: 176 passed before the final video-render assertion was added; focused cyberbrick/registry tests passed.
- Office production build passed.
- POSIX shell syntax check passed.
- Targeted ESLint for every changed/new office and cyberbrick TS/TSX file passed.
- Repository-wide office lint still reports the pre-existing unused _repeat parameter at office/src/cmd-vel-teleop.ts:40; that unrelated file is unchanged and was not modified for this task.

Final verification: the completed Office suite was rerun after the last cyberbrick video assertion and passed with 176 tests / 746 expectations. The full AWS suite passed 142 tests; focused cyberbrick catalog, certificate dispatch, and Office adapter tests passed; the Office production build, targeted lint, shell syntax check, and git diff whitespace check passed. Full Office lint remains blocked only by the pre-existing unused `_repeat` parameter in office/src/cmd-vel-teleop.ts, which this task did not modify.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added cyberbrick as a first-class device contract with unit-equivalent capabilities, REDCON rules, shadows, web adapter, and board-video resource. Added matching CloudFormation and Python catalog records, cyberbrick certificate-bundle dispatch with board-video KVS permissions, and Office registry/teleop/video support. Added parity, catalog, certificate, and UI tests. No AWS resources were changed and no deployment was performed.
<!-- SECTION:FINAL_SUMMARY:END -->
