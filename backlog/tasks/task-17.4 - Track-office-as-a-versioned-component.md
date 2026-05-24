---
id: TASK-17.4
title: Track office as a versioned component
status: Done
assignee:
  - codex
created_date: '2026-05-24 17:21'
updated_date: '2026-05-24 18:32'
labels: []
milestone: component-scoped release versioning
dependencies: []
references:
  - office/package.json
  - office/vite.config.ts
  - office/src/config.ts
documentation:
  - >-
    backlog/docs/architecture/component-scoped-release-versioning/doc-12 -
    Component-scoped-release-versioning.md
  - >-
    backlog/docs/milestones/component-scoped-release-versioning/doc-13 -
    Milestone-component-scoped-release-versioning.md
modified_files:
  - office/vite.config.ts
  - office/test/config-source.test.ts
  - release/src/txing_release/cli.py
  - release/tests/test_cli.py
  - docs/aws.md
  - docs/components/office.md
parent_task_id: TASK-17
ordinal: 29000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Office has an independent component version that is kept consistent across office-owned package/build metadata.
- [x] #2 The office Vite build injects the office component version without reading the removed root VERSION file.
- [x] #3 No GitHub release workflow or release asset publishing path is introduced for office.
- [x] #4 Office tests cover the package-based version source and preserve the no VITE_TXING_VERSION environment-variable rule.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Inspect current office version surfaces, update Vite to source __TXING_VERSION__ from office/package.json instead of the removed root VERSION file, keep release/versions/office and office package/runtime fallback consistency checks aligned, add focused tests proving package-based version source/no VITE_TXING_VERSION/no office release workflow, then run office and release validation.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented office component versioning by making the Vite build read office/package.json for __TXING_VERSION__ instead of ../VERSION. Kept release/versions/office, office/package.json, and office/src/config.ts runtime fallback aligned through the release helper, while removing office/vite.config.ts as a text-replaced fallback surface. Added office tests for package-based version injection, no VITE_TXING_VERSION, and absence of office GitHub release workflow references. Updated office/AWS docs to describe the package-based build version source.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-17.4 complete. Office now has an independent bare semver component version stored in release/versions/office and mirrored in office/package.json/runtime fallback; Vite injects the package version without reading root VERSION; no office GitHub release workflow or release asset path was introduced.
<!-- SECTION:FINAL_SUMMARY:END -->
