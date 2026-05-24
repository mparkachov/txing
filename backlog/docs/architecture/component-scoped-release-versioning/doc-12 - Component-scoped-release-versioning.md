---
id: doc-12
title: Component-scoped release versioning
type: specification
created_date: '2026-05-24 17:19'
updated_date: '2026-05-24 17:20'
---
# Component-scoped release versioning

## Goal

Split txing release versioning so independently moving product areas can release at independent cadences without forcing unrelated artifacts to rebuild or share a version.

The component streams are:

- `rig`: `txing-sparkplug-manager` and `txing-ble-connectivity`
- `lambda`: runtime Lambda artifacts `txing-witness-lambda`, `txing-cloud-rig-lambda`, and `txing-cloud-mcu-lambda`
- `unit`: `txing-unit-daemon`, `txing-unit-kvs-master`, and `txing-unit-hardware-worker`
- `office`: admin SPA version metadata only; Cloudflare Pages remains responsible for build and deploy

## Release model

The root `VERSION` file is removed. Each component has one committed version file under `release/versions/`:

- `release/versions/rig`
- `release/versions/lambda`
- `release/versions/unit`
- `release/versions/office`

Artifact-producing components publish immutable GitHub Releases with component-prefixed tags:

- `rig-vX.Y.Z`
- `lambda-vX.Y.Z`
- `unit-vX.Y.Z`

Each release workflow is manual, branch-dispatched, and builds only its component's artifacts. All artifacts inside one component release use the same component version. Workflows validate branch dispatch, semantic version format, duplicate release/tag absence, and monotonicity only against existing tags for the same component prefix.

Office has no GitHub release workflow. Its version is tracked in committed office version surfaces and consumed by the Vite build that Cloudflare Pages runs.

## Latest resolution

Board and rig hosts continue to install binaries through root-owned `mise` and GitHub release assets. The mise tool configs must use component-specific `version_prefix` values so `latest` resolves within the intended component stream:

- rig tools: `version_prefix = "rig-v"`
- unit tools: `version_prefix = "unit-v"`

If needed, set the mise GitHub backend option that forces `latest` to resolve from the component-filtered release list rather than GitHub's repo-wide `/latest` shortcut. `asset_pattern` alone is not enough because it selects an asset inside the release that has already been resolved.

Lambda publishing resolves `latest` against `lambda-v*` releases. Explicit `lambda-vX.Y.Z` and bare `X.Y.Z` are accepted for the Lambda stream. Exact legacy `vX.Y.Z` may remain accepted only to support manual rollback to old combined releases.

## Release helper

The release helper keeps only component-aware bump behavior:

```text
txing-release bump <component> <version>
```

When the target version differs from the component's current version, bump updates that component's managed version surfaces. When the target version is the same as the current version, bump performs a consistency audit and emits warnings for mismatches instead of failing as a release gate. There is no standalone `check` command and release workflows do not run a release consistency check.

## Forward-only policy

This is a forward-only release model change. No migration code or compatibility bridge is required. If old combined-release files, tags, docs, host mise config, or local operator habits need cleanup, the operator will handle that manually.

## Non-goals

- Do not publish office GitHub Releases.
- Do not add deployment automation for Cloudflare, AWS, rig, board, or firmware.
- Do not change firmware release behavior or include MCU firmware in the `unit` stream.
- Do not preserve automatic compatibility with mixed old/new component release layouts beyond allowing explicit legacy Lambda rollback references.
