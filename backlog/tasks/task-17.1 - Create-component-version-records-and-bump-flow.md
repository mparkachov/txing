---
id: TASK-17.1
title: Create component version records and bump flow
status: Done
assignee:
  - codex
created_date: '2026-05-24 17:21'
updated_date: '2026-05-24 17:41'
labels: []
milestone: component-scoped release versioning
dependencies: []
references:
  - release/src/txing_release/cli.py
  - release/justfile
documentation:
  - >-
    backlog/docs/architecture/component-scoped-release-versioning/doc-12 -
    Component-scoped-release-versioning.md
  - >-
    backlog/docs/milestones/component-scoped-release-versioning/doc-13 -
    Milestone-component-scoped-release-versioning.md
modified_files:
  - release/src/txing_release/cli.py
  - release/justfile
  - release/tests/test_cli.py
  - release/versions/rig
  - release/versions/lambda
  - release/versions/unit
  - release/versions/office
parent_task_id: TASK-17
ordinal: 26000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Rig, Lambda, unit, and office each have a committed semantic version source under release/versions.
- [x] #2 The release helper can bump exactly one named component and update that component's managed version surfaces.
- [x] #3 Running bump for a component's current version audits consistency and reports mismatches as warnings instead of acting as a required release gate.
- [x] #4 The standalone release check command and root VERSION dependency are absent from the release helper surface.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Implement component-scoped release helper support for rig, lambda, unit, and office version files under release/versions. Update bump to target exactly one component, refresh only that component's managed surfaces, turn same-version bump into a warning-only audit, remove the standalone check command/root VERSION dependency from release helper surface, and validate with focused release helper tests/commands.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented component-scoped version records and release helper bump behavior. The helper now accepts bump <component> <version>, updates only the selected component's managed version surfaces, audits same-version bumps with warning-only consistency reporting, and no longer exposes a standalone check command or reads the root VERSION file. Added focused unittest coverage for isolated component updates, warning-only audits, and check command removal.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added release/versions records for rig, lambda, unit, and office; converted txing-release bump to component-scoped behavior; removed the release helper check command; and added focused release helper tests.
<!-- SECTION:FINAL_SUMMARY:END -->
