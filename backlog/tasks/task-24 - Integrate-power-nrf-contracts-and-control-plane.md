---
id: TASK-24
title: Integrate power-nrf contracts and control plane
status: Done
assignee:
  - '@codex'
created_date: '2026-08-01 12:23'
updated_date: '2026-08-01 12:38'
labels: []
milestone: m-5
dependencies: []
documentation:
  - >-
    backlog/docs/architecture/power-nrf-thread-device/doc-33 -
    power-nrf-Thread-device-architecture.md
modified_files:
  - devices/power-nrf/manifest.toml
  - devices/power-nrf/aws
  - devices/power-nrf/web/power-nrf-adapter.tsx
  - devices/power-nrf/justfile
  - justfile
  - office/src/device-registry.ts
  - office/test/device-registry.test.ts
  - office/test/power-nrf-adapter.test.tsx
  - shared/aws/python/src/aws/type_catalog.py
  - shared/aws/template.yaml
  - shared/aws/python/tests/test_device_catalog.py
  - shared/aws/python/tests/test_device_registry.py
  - shared/aws/python/tests/test_enlist.py
  - shared/aws/python/tests/test_template_policy.py
  - shared/aws/python/tests/test_type_catalog.py
  - shared/aws/python/tests/test_versioning.py
type: feature
ordinal: 70000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deliver power-nrf as a first-class raspi device type with the same Sparkplug, Thread, Power, and REDCON contract as power-si.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Device manifests, defaults, and Sparkplug Thread Power named-shadow contracts define power-nrf.
- [x] #2 Catalog, enlistment, CloudFormation type catalog, root just module, and Office registry adapter accept Power nRF.
- [x] #3 REDCON 4 publishes Sparkplug and Thread, while REDCON 3 additionally publishes Power.
- [x] #4 Existing power and power-si behavior remains unchanged and integration tests cover the new type.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Trace the established power-si type across manifests, named shadows, type catalogs, enlistment/template generation, root just modules, and the Office registry. Add power-nrf as a parallel raspi type with identical REDCON capability rules, preserving existing types and topics. Add focused tests for type registration, generated configuration, Office selection, and REDCON-based capability publication; run the relevant suites before handoff.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added power-nrf as a raspi type with Sparkplug, Thread, and Power contracts; catalog and CloudFormation registration; root Just module; and a Power nRF Office adapter. REDCON 4 exposes Sparkplug and Thread, while REDCON 3 adds Power. Focused AWS catalog, enlistment, registry, template, versioning, and Office adapter tests pass.
<!-- SECTION:FINAL_SUMMARY:END -->
