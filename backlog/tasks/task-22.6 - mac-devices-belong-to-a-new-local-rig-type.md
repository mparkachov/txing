---
id: TASK-22.6
title: mac devices belong to a new local rig type
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 19:40'
updated_date: '2026-07-03 19:48'
labels: []
milestone: m-1
dependencies: []
references:
  - shared/aws/python/src/aws/type_catalog.py
  - shared/aws/template.yaml
  - devices/mac/manifest.toml
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 55000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Introduce a 'local' rig type for the standalone rig daemons run manually on the development Mac via just rig::start (no systemd, no autostart, no release packaging). The mac device type is compatible only with local rigs, not raspi. Like raspi, a local rig is NDEATH-projected whenever its process is not running and publishes NBIRTH redcon=1 when started.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The local rig type exists across the AWS type catalog surfaces with sparkplug capability and REDCON command levels 1,4, and rig certificate bundles can be generated for local rig things.
- [x] #2 The mac device type declares compatibility with local rigs only, and catalog/enlist/office tests cover the local rig placement.
- [x] #3 Documentation describes the local rig type and the mac registration flow through it.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented: local rig type added to RIG_TYPE_DEFINITIONS (display 'Local Rig', default name 'dev', sparkplug, redcon 1/4, no host services), shared/aws/thing-type-capabilities.json, and LocalTypeCatalogV2 in template.yaml. MacTypeCatalogV2 re-homed to /txing/town/local/mac with rigType local and DependsOn LocalTypeCatalogV2; devices/mac/manifest.toml compatible_rig_types=[local]. Cert dispatch accepts rigType:local via the existing rig bundle (rig-daemon.env.template). Runtime is untouched: the rig daemons resolve their own thing type at runtime and load /txing/town/<rigType>/<deviceType>, and NBIRTH redcon=1 on start plus NDEATH via will/graceful shutdown come from the standalone daemon behavior shared with raspi. Docs updated: sparkplug-lifecycle (edge model + local lifecycle bullet), components/rig.md (local rig section + registration), docs/README.md capability list, devices/mac/README.md, backlog architecture doc-23. Validation: shared/aws pytest 139 passed; office bun test 168 passed; rig go test passes for all packages except the pre-existing macOS-environmental abort in cmd/txing-ble-connectivity (unchanged code, fails identically on a clean tree).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
mac devices now belong to a new 'local' rig type: the standard standalone rig daemons registered as a local rig thing and run manually on the development Mac via just rig::start, with no systemd/autostart. Catalog surfaces (RIG_TYPE_DEFINITIONS, LocalTypeCatalogV2, thing-type-capabilities.json), the mac manifest/catalog placement (/txing/town/local/mac), rig cert bundles for local things, tests, and documentation were all updated. Lifecycle matches raspi expectations: NBIRTH redcon=1 while the process runs, NDEATH when it stops. User-run rollout: just aws::deploy, just aws::deploy-rig <town-id> local <name>, just aws::cert <local-rig-id>, then register mac devices under the local rig.
<!-- SECTION:FINAL_SUMMARY:END -->
