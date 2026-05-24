---
id: TASK-17.5
title: Retire root VERSION references from release docs and tests
status: Done
assignee:
  - codex
created_date: '2026-05-24 17:21'
updated_date: '2026-05-24 18:44'
labels: []
milestone: component-scoped release versioning
dependencies: []
references:
  - docs/artifacts.md
  - docs/development.md
  - shared/aws/python/tests/test_versioning.py
documentation:
  - >-
    backlog/docs/architecture/component-scoped-release-versioning/doc-12 -
    Component-scoped-release-versioning.md
  - >-
    backlog/docs/milestones/component-scoped-release-versioning/doc-13 -
    Milestone-component-scoped-release-versioning.md
modified_files:
  - VERSION
  - justfile
  - rig/justfile
  - devices/unit/daemon/justfile
  - docs/artifacts.md
  - docs/development.md
  - docs/agent-guidance/editing-boundaries.md
  - shared/aws/python/src/aws_admin/publish_release/core.py
  - shared/aws/python/tests/test_versioning.py
  - shared/aws/python/tests/test_template_policy.py
parent_task_id: TASK-17
ordinal: 30000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Repository release documentation describes component version files, component-prefixed tags, and office's Cloudflare-only version tracking.
- [x] #2 Repository-wide tooling and tests no longer require root VERSION, TXING_VERSION, or TXING_VERSION_BASE.
- [x] #3 Release/versioning tests cover component-scoped workflows, helper behavior, latest resolution, and forward-only cleanup notes.
- [x] #4 Final validation demonstrates no stale root VERSION release-process references remain in active docs, workflows, or tests.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Audit active release docs, workflows, root tooling, and versioning tests for stale root VERSION/TXING_VERSION/TXING_VERSION_BASE assumptions. Remove remaining root-version release process dependencies, update docs to describe component version files, component-prefixed tags, and office Cloudflare-only tracking, strengthen tests for component workflows/helper/latest/forward-only cleanup, then validate with targeted searches and release/versioning test suites.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Removed the root VERSION file and retired root-version exports from repository tooling. The root justfile now exposes _project-git-env for Git diagnostics only; _project-aws-env no longer exports TXING_VERSION or TXING_VERSION_BASE. Local rig and unit build recipes now read release/versions/rig and release/versions/unit. Release docs now describe component version files, component-prefixed tags, Lambda latest behavior, forward-only host cleanup, and office Cloudflare-only version tracking. Versioning/template-policy tests now assert the component-scoped workflows, helper behavior, latest resolution coverage, forward-only cleanup notes, root VERSION removal, and absence of root TXING_VERSION tooling.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-17.5 complete. Root VERSION is removed, active release docs/tests/tooling no longer require root VERSION/TXING_VERSION/TXING_VERSION_BASE, component-scoped docs and tests cover rig/lambda/unit/office version streams, and final stale-reference validation passes.
<!-- SECTION:FINAL_SUMMARY:END -->
