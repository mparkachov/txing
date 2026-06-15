---
id: TASK-19
title: 'Milestone: multi-user office access'
status: Done
assignee:
  - '@codex'
created_date: '2026-06-15 09:05'
updated_date: '2026-06-15 10:21'
labels: []
milestone: multi-user office access
dependencies: []
references:
  - office/src/App.tsx
  - shared/aws/template.yaml
documentation:
  - >-
    backlog/docs/architecture/multi-user-office-access/doc-17 -
    Multi-user-office-access-architecture.md
  - >-
    backlog/docs/milestones/multi-user-office-access/doc-18 -
    Milestone-multi-user-office-access.md
modified_files:
  - office/src/App.tsx
  - office/src/config.ts
  - office/src/vite-env.d.ts
  - office/justfile
  - office/.env.example
  - office/test/app-source.test.ts
  - office/test/config-source.test.ts
  - docs/aws.md
  - docs/components/office.md
  - shared/aws/template.yaml
  - shared/aws/python/tests/test_template_policy.py
  - shared/aws/python/tests/test_versioning.py
  - >-
    backlog/docs/architecture/multi-user-office-access/doc-17 -
    Multi-user-office-access-architecture.md
ordinal: 36000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Office accepts any signed-in user from the configured Cognito User Pool without an email allow-list rejection.
- [x] #2 All accepted users continue to use the existing Identity Pool authenticated role for IoT, Sparkplug, MCP, and KVS viewer operations.
- [x] #3 Office runtime and deployment documentation no longer require VITE_ADMIN_EMAIL as an access-control input.
- [x] #4 The milestone includes validation results for office tests/build and relevant shared AWS Python tests.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify both child tasks TASK-19.1 and TASK-19.2 are done and cover the parent acceptance criteria.\n2. Scan the current repository docs/config for stale VITE_ADMIN_EMAIL allow-list references and old single-admin wording.\n3. Rerun the relevant office tests/build and shared AWS Python tests.\n4. Check all parent acceptance criteria and close TASK-19 with validation and rollout notes.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Closeout audit: TASK-19.1 and TASK-19.2 are Done with all child acceptance criteria checked. The office email allow-list gate is removed; VITE_ADMIN_EMAIL is no longer required by office config, generated env, env examples, or Cloudflare docs; AWS and office docs now state Cognito User Pool membership is the access boundary and AdminEmail/WebExpectedAdminEmail/create-admin-user are seed-admin bootstrap only. Cleaned up the architecture planning doc so it reflects the implemented state rather than pre-implementation current state. Validation rerun at parent closeout: cd office && bun test passed (146 tests); cd office && bun run build passed; UV_CACHE_DIR=./tmp/uv-cache uv run --project shared/aws/python pytest shared/aws/python/tests/test_template_policy.py shared/aws/python/tests/test_versioning.py passed (51 tests).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Multi-user office access is implemented and documented. Office treats configured Cognito User Pool membership as the access boundary, preserves the existing Identity Pool authenticated role for IoT, Sparkplug, MCP, and KVS viewer operations, and no longer requires VITE_ADMIN_EMAIL. AWS/office docs and template metadata describe AdminEmail/WebExpectedAdminEmail/create-admin-user as seed-admin bootstrap support only. Validation passed: office tests, office production build, and shared AWS Python template/versioning tests. Rollout: redeploy Office through Cloudflare Pages; apply the normal AWS stack deployment path only if carrying the template metadata/tag wording changes into AWS.
<!-- SECTION:FINAL_SUMMARY:END -->
