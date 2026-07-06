---
id: TASK-18.3
title: Remove unused shared AWS Python MQTT helper
status: Done
assignee:
  - '@codex'
created_date: '2026-05-30 08:17'
updated_date: '2026-05-30 09:20'
labels: []
milestone: MQTT5 retained message expiry
dependencies: []
references:
  - shared/aws/python/src/aws/mqtt.py
  - shared/aws/python/tests/test_mqtt.py
documentation:
  - >-
    backlog/docs/architecture/mqtt5-retained-message-expiry/doc-14 -
    MQTT5-retained-message-expiry-architecture.md
  - >-
    backlog/docs/milestones/mqtt5-retained-message-expiry/doc-15 -
    Milestone-MQTT5-retained-message-expiry.md
  - >-
    backlog/docs/constraints/mqtt-retained-message-policy/doc-16 -
    Constraints-MQTT-retained-message-policy.md
parent_task_id: TASK-18
ordinal: 34000
---

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Shared AWS Python has no exported MQTT client wrapper or MQTT tests.
- [x] #2 The shared AWS Python package no longer depends on awsiotsdk or awscrt for MQTT/WebSocket support.
- [x] #3 Shared AWS Python tests pass after removal.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Re-scan shared AWS Python, production code, and tests for MQTT wrapper references.
2. Remove the unused shared AWS Python MQTT wrapper and its test module.
3. Remove MQTT-only exports and AWS CRT credential-provider bridge code.
4. Remove awsiotsdk/awscrt from shared AWS Python dependencies and lockfile.
5. Run shared AWS Python tests and record validation.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
User clarified the shared Python MQTT path was intentionally removed previously and should not be retained because it is not used by production code. Re-analysis found AwsIotWebsocketConnection, AwsIotWebsocketSyncConnection, AwsMqttConnectionConfig, AWS_IOT_SDK_IMPORT_ERROR, awsiotsdk, awscrt, mqtt5_client_builder, and mqtt_connection_builder references only in the shared MQTT wrapper, exports, and tests. Removed shared/aws/python/src/aws/mqtt.py and shared/aws/python/tests/test_mqtt.py; removed MQTT exports from aws.__init__; removed the MQTT-only AwsCredentialsBridge/AWS CRT credential provider from auth.py; removed awsiotsdk from pyproject.toml and lock, which also removed awscrt. Validation: UV_CACHE_DIR=/Users/Maxim/Developer/txing/tmp/uv-cache uv run --project /Users/Maxim/Developer/txing/shared/aws/python pytest passed with 133 tests; UV_CACHE_DIR=/Users/Maxim/Developer/txing/tmp/uv-cache uv run --project shared/aws/python pytest shared/aws/python/tests passed with 133 tests. rg found no remaining shared AWS MQTT wrapper, awsiotsdk, or awscrt references.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Removed the unused shared AWS Python MQTT helper and its MQTT-only dependencies/exports/tests. Shared AWS Python now has no MQTT client path; tests pass with 133 tests.
<!-- SECTION:FINAL_SUMMARY:END -->
