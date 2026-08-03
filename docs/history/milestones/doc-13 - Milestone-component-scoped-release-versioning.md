---
id: doc-13
title: 'Milestone: component-scoped release versioning'
type: guide
created_date: '2026-05-24 17:19'
updated_date: '2026-05-24 17:20'
---
# Milestone: component-scoped release versioning

## Outcome

The repository uses independent, forward-only version streams for rig, Lambda, unit, and office. Rig, Lambda, and unit releases are manual component workflows with immutable component-prefixed GitHub Releases. Office tracks its own version for Cloudflare-built UI metadata without producing GitHub release artifacts.

## Scope

In scope:

- Component version files under `release/versions/`
- Component-aware release helper bump behavior
- Three manual GitHub Actions release workflows for rig, Lambda, and unit
- Lambda publisher latest resolution for `lambda-v*`
- Host mise config/docs for rig and unit latest resolution
- Office package/Vite version metadata sourced from office-owned version data
- Tests and docs that describe the new release process

Out of scope:

- Code deployment to AWS, Cloudflare, rig hosts, or board hosts
- Firmware flashing or MCU artifact release work
- Migration automation for old combined releases, old host config, or old tags
- Preserving the removed root `VERSION` as a compatibility alias

## Constraints

- The change is forward-only; manual cleanup is acceptable where old release state remains.
- Release workflows stay manual and runnable from any branch.
- All artifacts in one component release must use exactly that component's version.
- Release workflows publish artifacts only; they do not bump versions, commit, push, deploy to AWS, deploy to hosts, or deploy office.
- GitHub Release/tag immutability remains enforced per component version.

## Exit criteria

- A rig release can produce rig artifacts at a version such as `0.12.10` without building Lambda, unit, or office artifacts.
- A Lambda release can produce Lambda artifacts at a version such as `0.12.0` and `just aws::publish latest` resolves the newest `lambda-v*` release.
- A unit release can produce unit artifacts at a version such as `0.13.0` without building rig, Lambda, or office artifacts.
- Office can carry its own tracked version and Cloudflare builds inject that office version into the SPA.
- Root `VERSION` is gone and tests/docs no longer require it.
