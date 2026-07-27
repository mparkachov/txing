---
id: TASK-21.1
title: power-si catalog and UI contract is first-class
status: Done
assignee:
  - '@Codex'
created_date: '2026-06-20 07:12'
updated_date: '2026-06-20 09:16'
labels: []
milestone: m-0
dependencies: []
references:
  - devices/power/manifest.toml
  - shared/aws
  - office/src/device-registry.ts
documentation:
  - >-
    backlog/docs/architecture/power-si-thread-device/doc-21 -
    power-si-Thread-device-type-architecture.md
parent_task_id: TASK-21
priority: high
ordinal: 45000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Register power-si as a first-class txing device type across manifests, shadow schemas/defaults, AWS/shared catalog generation, and Office UI while preserving the existing power device contract.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 devices/power-si defines the public type slug, display metadata, sparkplug/thread/power capabilities, REDCON 4/3 rules, and sparkplug/thread/power shadow defaults/schemas.
- [x] #2 Shared AWS catalog, registry, enlist/default-shadow, and release/versioning tests include power-si without changing existing power behavior.
- [x] #3 Office registers power-si with the existing power model/panel behavior and tests cover the new adapter.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Read local AGENTS guidance for devices, shared/aws, and office before edits.\n2. Mirror the existing power device contract into a new power-si device definition with sparkplug/thread/power shadows and REDCON rules.\n3. Register power-si in shared AWS type/catalog paths and tests without changing the existing power type.\n4. Register power-si in Office by reusing the existing power model/panel behavior and add registry test coverage.\n5. Run focused shared AWS and Office validation; update TASK-21.1 acceptance status and summary only if all criteria are proven.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented power-si first-class contract surface: added devices/power-si manifest, sparkplug/thread/power shadow schemas/defaults, minimal device justfile, and a Power SI web adapter reusing power behavior. Registered power-si in shared AWS type catalog generation, CloudFormation type catalog parameters, root just module list, Office adapter registry, and focused tests. Validation passed: full shared/aws/python pytest suite (137 passed), full office bun test suite (163 passed), office bun run build, just --list power-si visibility, and git diff --check.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-21.1 completed. power-si is registered as a first-class catalog/UI contract with sparkplug/thread/power capabilities, REDCON 4/3 rules, named shadow defaults/schemas, AWS type catalog and template coverage, enlist/registry/default-shadow tests, release/versioning boundary coverage, and Office adapter/test coverage. Existing power behavior remains covered by the same full AWS and Office suites.
<!-- SECTION:FINAL_SUMMARY:END -->
