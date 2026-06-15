---
id: TASK-19.2
title: Document Cognito-console office enrollment
status: Done
assignee:
  - '@codex'
created_date: '2026-06-15 09:06'
updated_date: '2026-06-15 10:17'
labels: []
milestone: multi-user office access
dependencies: []
references:
  - docs/aws.md
  - docs/components/office.md
  - shared/aws/template.yaml
documentation:
  - >-
    backlog/docs/architecture/multi-user-office-access/doc-17 -
    Multi-user-office-access-architecture.md
  - >-
    backlog/docs/milestones/multi-user-office-access/doc-18 -
    Milestone-multi-user-office-access.md
modified_files:
  - docs/aws.md
  - docs/components/office.md
  - shared/aws/template.yaml
  - shared/aws/python/tests/test_template_policy.py
  - shared/aws/python/tests/test_versioning.py
parent_task_id: TASK-19
ordinal: 38000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 AWS and office docs state that configured Cognito User Pool membership is the office access boundary.
- [x] #2 Docs explain that operators add users in the AWS Cognito console and that users sign in through the existing Cognito Hosted UI flow.
- [x] #3 AdminEmail, WebExpectedAdminEmail, and create-admin-user are described only as seed-admin/bootstrap support and not as an office allow-list.
- [x] #4 Cloudflare Pages environment-variable docs omit VITE_ADMIN_EMAIL while preserving all required Cognito, IoT, town, and Sparkplug values.
- [x] #5 Relevant shared AWS Python tests pass or are updated to enforce the new seed-admin wording without changing AWS identity resources.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Update docs/aws.md and docs/components/office.md to state that the configured Cognito User Pool is the office access boundary, that operators add users in the AWS Cognito console, and that users sign in through the existing Hosted UI flow.\n2. Remove VITE_ADMIN_EMAIL from Cloudflare Pages environment-variable docs while preserving the required Cognito, IoT, town, and Sparkplug variables.\n3. Update shared/aws/template.yaml descriptions/tags/output metadata so AdminEmail/WebExpectedAdminEmail are seed-admin bootstrap values, not a SPA allow-list, without changing Cognito/User Pool/Identity Pool resources or permissions.\n4. Update shared AWS Python tests that assert the old wording or Cloudflare env list, then run the relevant Python tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Updated AWS and office docs to state that configured Cognito User Pool membership is the office access boundary, operators add users in the AWS Cognito console, and users sign in through the existing Cognito Hosted UI flow. Removed VITE_ADMIN_EMAIL from Cloudflare Pages environment-variable docs. Updated CloudFormation metadata for AdminEmail/WebExpectedAdminEmail to describe seed-admin bootstrap support rather than a SPA allow-list. Added Python assertions for the new docs/template contract. Validation: UV_CACHE_DIR=./tmp/uv-cache uv run --project shared/aws/python pytest shared/aws/python/tests/test_template_policy.py shared/aws/python/tests/test_versioning.py passed (51 tests).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
AWS and office docs now document Cognito User Pool enrollment as the office access model and describe AdminEmail/WebExpectedAdminEmail/create-admin-user only as seed-admin bootstrap support. Cloudflare Pages env docs no longer list VITE_ADMIN_EMAIL, and shared AWS Python tests enforce the new wording.
<!-- SECTION:FINAL_SUMMARY:END -->
