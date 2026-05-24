---
id: TASK-17
title: 'Milestone: component-scoped release versioning'
status: Done
assignee:
  - codex
created_date: '2026-05-24 17:20'
updated_date: '2026-05-24 18:53'
labels: []
milestone: component-scoped release versioning
dependencies: []
references:
  - .github/workflows/release.yml
  - release/src/txing_release/cli.py
  - shared/aws/python/src/aws_admin/publish_release/core.py
documentation:
  - >-
    backlog/docs/architecture/component-scoped-release-versioning/doc-12 -
    Component-scoped-release-versioning.md
  - >-
    backlog/docs/milestones/component-scoped-release-versioning/doc-13 -
    Milestone-component-scoped-release-versioning.md
modified_files:
  - VERSION
  - release/versions/rig
  - release/versions/lambda
  - release/versions/unit
  - release/versions/office
  - .github/workflows/release.yml
  - .github/workflows/release-rig.yml
  - .github/workflows/release-lambda.yml
  - .github/workflows/release-unit.yml
  - release/src/txing_release/cli.py
  - shared/aws/python/src/aws_admin/publish_release/core.py
  - docs/artifacts.md
  - docs/development.md
  - docs/components/rig.md
  - docs/components/board.md
  - docs/components/office.md
ordinal: 25000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Rig, Lambda, unit, and office have independent committed version streams with no root VERSION dependency.
- [x] #2 Rig, Lambda, and unit artifact releases are published by separate manual branch-dispatched workflows.
- [x] #3 Office version metadata is tracked independently without a GitHub release workflow.
- [x] #4 Forward-only release docs cover manual cleanup for old combined-release state where needed.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Closed after all five child tasks TASK-17.1 through TASK-17.5 were Done with checked acceptance criteria. Milestone audit verified independent release/versions component files, removal of the root VERSION file, three component release workflows for rig/lambda/unit, no office GitHub release workflow, component-scoped latest resolution docs/tests, and forward-only manual cleanup guidance. User confirmed host mise configs were updated manually.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-17 complete. The repository now uses independent component version streams for rig, lambda, unit, and office; rig/lambda/unit publish via separate component-prefixed manual workflows; office is Cloudflare-only version metadata; root VERSION/TXING_VERSION release dependencies are retired; and docs/tests cover forward-only cleanup expectations.
<!-- SECTION:FINAL_SUMMARY:END -->
