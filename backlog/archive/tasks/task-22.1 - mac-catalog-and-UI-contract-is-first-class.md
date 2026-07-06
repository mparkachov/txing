---
id: TASK-22.1
title: mac catalog and UI contract is first-class
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 07:44'
updated_date: '2026-07-03 19:14'
labels: []
milestone: m-1
dependencies: []
references:
  - devices/unit/manifest.toml
  - shared/aws/template.yaml
  - shared/aws/python/src/aws/type_catalog.py
  - shared/aws/scripts/aws_lib.sh
  - office/src/device-registry.ts
documentation:
  - >-
    backlog/docs/architecture/mac-device-type/doc-23 -
    Mac-device-type-architecture.md
parent_task_id: TASK-22
priority: high
ordinal: 50000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Register mac as a first-class txing device type across the device manifest, shadow schemas/defaults, AWS type catalog (CloudFormation + python catalog generation + tests), certificate bundle generation, and the office UI, without changing existing device types. The office adapter renders the mac device with status detail and a video panel gated to REDCON 1, with drive control disabled.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The mac device type declares sparkplug/power/board/mcp/video capabilities, REDCON command levels 4-1, the unit-shaped redcon rules, per-capability shadow schema/default files, a web adapter, and the board video channel resource.
- [x] #2 AWS catalog deployment material and the python type catalog include mac with identical capability data, and existing shared AWS tests plus new mac coverage pass.
- [x] #3 Certificate bundle generation for a mac thing produces the daemon config bundle including KVS master permissions on the device video channel.
- [x] #4 Office shows a registered mac device with the video route available at REDCON 1 and no drive controls, covered by adapter tests.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. devices/mac: manifest.toml (type mac, capabilities sparkplug/power/board/mcp/video, redcon levels 4-1, unit-shaped rules, web adapter, board_video resource), README.md, daemon.env.template, aws/ shadow schema+default pairs for all five capabilities (from devices/unit/aws).
2. shared/aws/template.yaml: MacTypeCatalogV2 Custom::TxingTypeCatalog mirroring the manifest (CatalogBasePath /txing/town/raspi/mac, sparkplug defaultPayload deviceId mac-local).
3. shared/aws/python: add mac to the device tuple in type_catalog.py build_type_records; extend test_template_policy.py and any device-catalog tests that enumerate types.
4. shared/aws/scripts/aws_lib.sh: deviceType:mac cert-bundle case (TxingDaemonIotPolicy, txing-daemon-<thing> role with ConnectAsMaster on <thing>-board-video, role alias, renders devices/mac/daemon.env.template); pass the template path through the shared/aws justfile cert recipe.
5. Office: devices/mac/web mac-adapter.tsx + MacPanel.tsx + mac-model.ts (video at REDCON 1, no drive control) registered in office/src/device-registry.ts, with adapter tests.
6. Validate: shared/aws python tests, office tests/build, rig go test (registry/manifest consumers), no changes to other device types.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementation notes:
- devices/mac created from the template pattern: manifest.toml (capabilities sparkplug/power/board/mcp/video, redcon levels 4-1, rules 4=[sparkplug] 3=[+power] 2=[+board,mcp] 1=[+video], web adapter, board_video channel), README.md, daemon.env.template, aws/ shadow schema+default pairs for all five capabilities (copied from devices/unit/aws with mac-specific $id/title and sparkplug deviceId mac-local).
- shared/aws/template.yaml: MacTypeCatalogV2 mirrors the manifest at /txing/town/raspi/mac.
- shared/aws/python/src/aws/type_catalog.py: mac added to the build_type_records device tuple.
- Cert bundle: txing_cert_generate_unit_bundle generalized to txing_cert_generate_device_daemon_bundle (bundle_type parameter, txing_cert_write_daemon_env rename); deviceType:mac dispatch renders devices/mac/daemon.env.template with bundleType mac-daemon; shared/aws justfile cert recipe passes the mac template path. IAM/KVS policy path is byte-identical to unit (ConnectAsMaster on <thing>-board-video).
- Office: devices/mac/web/{mac-adapter.tsx,MacPanel.tsx,mac-model.ts} registered in office/src/device-registry.ts; video at REDCON 1 only, canUseDriveControl always false; MacPanel is a trimmed unit panel (network indicator + MCP transport glyph + video, no teleop/battery/BLE/take-control).
- docs/README.md capability list updated (added mac and the previously missing power-si).
- Validation: shared/aws python suite 139 passed (incl. new mac manifest/type-catalog/template/enlist coverage); office bun test 168 passed (new mac-adapter tests + registry coverage); office production build OK; sh -n aws_lib.sh OK; daemon.env rendering exercised locally through txing_cert_write_daemon_env. Live 'just aws::deploy' + 'just aws::cert <mac-thing>' remain user-run steps per repo AWS gates.
- Pre-existing unrelated lint failure in office/src/cmd-vel-teleop.ts (unused _repeat) left untouched.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
mac is now a first-class txing device type across all catalog surfaces. devices/mac carries the manifest (sparkplug/power/board/mcp/video, REDCON 4-1 with unit-shaped rules minus ble, web adapter, {device_id}-board-video resource), per-capability shadow schemas/defaults, a README, and the daemon.env template. The AWS side is triple-synced: MacTypeCatalogV2 in shared/aws/template.yaml, the python type-catalog device tuple, and the manifest all carry identical capability data, so registry validation and the enlist Lambda (thing + KVS signaling channel creation) work for mac things unchanged. Certificate bundles: the unit bundle generator was generalized into txing_cert_generate_device_daemon_bundle and dispatches deviceType:mac to render devices/mac/daemon.env.template with the same TxingDaemonIotPolicy, txing-daemon-<thing> role (incl. kinesisvideo ConnectAsMaster on the device channel), and role alias. Office registers the mac adapter: video route gated to REDCON 1, drive control disabled everywhere, trimmed status panel. Existing device types are untouched. Evidence: shared/aws pytest 139 passed, office bun test 168 passed, office build clean, aws_lib.sh syntax-checked, daemon.env rendering exercised locally. User-run rollout: just aws::deploy, then just aws::deploy-device <rig-id> mac <name>, just aws::cert <thing-id>, and per-shadow just aws::init-shadow.
<!-- SECTION:FINAL_SUMMARY:END -->
