---
id: TASK-17.3
title: Resolve latest releases by component
status: Done
assignee:
  - codex
created_date: '2026-05-24 17:21'
updated_date: '2026-05-24 18:28'
labels: []
milestone: component-scoped release versioning
dependencies: []
references:
  - rig/install-mise-tools.sh
  - shared/aws/python/src/aws_admin/publish_release/core.py
  - shared/aws/justfile
documentation:
  - >-
    backlog/docs/architecture/component-scoped-release-versioning/doc-12 -
    Component-scoped-release-versioning.md
  - >-
    backlog/docs/milestones/component-scoped-release-versioning/doc-13 -
    Milestone-component-scoped-release-versioning.md
modified_files:
  - rig/install-mise-tools.sh
  - shared/aws/python/src/aws_admin/publish_release/core.py
  - shared/aws/justfile
  - shared/aws/python/tests/test_publish.py
  - shared/aws/python/tests/test_versioning.py
  - docs/components/rig.md
  - docs/components/board.md
  - docs/aws.md
  - docs/development.md
  - docs/artifacts.md
parent_task_id: TASK-17
ordinal: 28000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Rig host mise config resolves latest rig binaries from rig-v* releases, not from the repo-wide latest release.
- [x] #2 Unit host mise config resolves latest unit binaries from unit-v* releases, not from the repo-wide latest release.
- [x] #3 Lambda publish commands resolve latest runtime Lambda assets from lambda-v* releases and still accept explicit Lambda version references.
- [x] #4 Operator-facing docs explain the component-specific latest behavior and forward-only manual cleanup expectation.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Update host and Lambda release resolution so latest is scoped by component. Add rig-v and unit-v mise version_prefix settings in rig installer and board/rig operator docs; change Lambda publisher normalization and GitHub latest lookup to use lambda-v* for latest while accepting lambda-vX.Y.Z and bare X.Y.Z, with exact legacy vX.Y.Z still accepted; update shared AWS just release validation and focused tests/docs for forward-only manual cleanup expectations.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Updated rig mise config to set version_prefix = "rig-v" for both rig tools. Updated board/rig/artifact/development/AWS docs so operators know latest is component-scoped and old host configs require forward-only manual replacement. Changed Lambda release normalization so latest resolves by listing GitHub releases and selecting the highest lambda-v* SemVer release; explicit lambda-vX.Y.Z and bare X.Y.Z resolve to the Lambda stream, while legacy vX.Y.Z remains accepted. Updated AWS just release argument validation and focused tests.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Component-scoped latest resolution is implemented for rig mise configs, documented unit mise configs, and Lambda publishing. Operator docs now describe rig-v/unit-v/lambda-v latest behavior and manual forward-only cleanup expectations.
<!-- SECTION:FINAL_SUMMARY:END -->
