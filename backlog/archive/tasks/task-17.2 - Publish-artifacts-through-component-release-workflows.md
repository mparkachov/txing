---
id: TASK-17.2
title: Publish artifacts through component release workflows
status: Done
assignee:
  - codex
created_date: '2026-05-24 17:21'
updated_date: '2026-05-24 17:52'
labels: []
milestone: component-scoped release versioning
dependencies: []
references:
  - .github/workflows/release-rig.yml
  - .github/workflows/release-lambda.yml
  - .github/workflows/release-unit.yml
documentation:
  - >-
    backlog/docs/architecture/component-scoped-release-versioning/doc-12 -
    Component-scoped-release-versioning.md
  - >-
    backlog/docs/milestones/component-scoped-release-versioning/doc-13 -
    Milestone-component-scoped-release-versioning.md
modified_files:
  - .github/workflows/release.yml
  - .github/workflows/release-rig.yml
  - .github/workflows/release-lambda.yml
  - .github/workflows/release-unit.yml
  - shared/aws/python/tests/test_versioning.py
parent_task_id: TASK-17
ordinal: 27000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Rig, Lambda, and unit each have a separate manual workflow runnable from any branch.
- [x] #2 Each workflow reads its component version, enforces component-prefixed immutable tags, and compares monotonicity only within that component tag stream.
- [x] #3 Each workflow publishes only its component artifact set and does not build or upload artifacts from other components.
- [x] #4 The old all-component release workflow cannot be accidentally dispatched.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Split the old all-component GitHub release workflow into separate manual rig, lambda, and unit workflows. Each workflow will read release/versions/<component>, validate branch dispatch and strict semver, enforce immutable component-prefixed tags, compare monotonicity only against tags with its own prefix, build/upload only that component's artifacts, and publish only those assets. Retire the old all-component workflow dispatch surface and update focused versioning tests to assert the new workflow boundaries.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Split the former all-component release workflow into manual rig, lambda, and unit workflows. Each workflow reads release/versions/<component>, builds a component-prefixed tag using <component>-v, rejects non-branch dispatch, checks monotonicity only against tags matching its own prefix, rejects existing releases/tags for that exact component tag, and publishes only its component asset set. Removed the old .github/workflows/release.yml dispatch surface and updated the focused versioning test to assert component workflow boundaries.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added separate rig, lambda, and unit release workflows with component-scoped version/tag validation and component-only artifact publishing; removed the old all-component release workflow; updated release workflow tests.
<!-- SECTION:FINAL_SUMMARY:END -->
