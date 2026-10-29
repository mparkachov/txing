# Local ARM64 cloud artifact validation

Recorded 2026-10-29 for #168. These checks ran through the existing Lima engine
using `nerdctl.lima`; they establish local Linux ARM64 build/package behavior.
AWS deployment, snapshot restoration and device/cloud acceptance remain manual
under the [rollout runbook](constraints/agent-rollout.md) and
[witness watch contract](constraints/agent-watch.md).

The capability correction later on 2026-10-29 changes registry authorization and
Sparkplug agent availability. The artifacts recorded below predate that change
and must be rebuilt before rollout.

## Source and tooling

- Source revision: `c13a157f96d0f968f6d4939aa00fb507388931cc` with the uncommitted
  #168 implementation. This is not a published immutable release.
- Verified source-manifest/build ID shared by controller and runtime:
  `d014d8554b489670e86162e055b6e03af456970f0757236dcdb9bea3c660e0ac`.
- Engine: nerdctl `v2.4.1`, BuildKit `v0.33.1`, containerd `v2.4.1`, Linux ARM64.
- A scratch-stage local-export check and an isolated Alpine bind-mount check
  passed before the artifact builds.

## Controller ZIP

`just agent::controller-package` completed successfully through `nerdctl.lima`.
All eight CTest targets passed in the Linux ARM64 build. `readelf`/`file` identify
the exported bootstrap as an AArch64 Linux ELF. The ZIP integrity check passes.

- ZIP: `tmp/agent-controller.rnNnn5/artifact/controller.zip`.
- SHA-256: `ce771004d64f8bbac1dce0af575ad6c7587871f756aa40e9ef55f13eb4b244ab`.
- Validation runtime:
  `public.ecr.aws/lambda/provided@sha256:e0a5c70ae7962e83bcc5a6deada474a1646e2d0df5136607c0f21190403272ee`.
- In that runtime, with networking disabled, dependency loading found every
  library and bootstrap startup without a Lambda runtime endpoint produced the
  expected `Lambda runtime API address is invalid` failure.
- `provenance/` retains engine versions, source hashes, package versions,
  ELF details, runtime digest, link results and bootstrap output.
- Full successful build log: `tmp/agent-controller-lima-build-final.log`.

## Production runtime image

The documented command completed successfully:

```sh
nerdctl.lima build --platform linux/arm64 --progress plain \
  --tag txing-agent-cloud:local tmp/agent-cloud-package
```

All eight CTest targets passed in this build too. The final image's library
checks passed and image inspection confirms Linux ARM64, user `10001:10001`,
and the mandatory `--require-assignment` entry point.

- Local image digest:
  `txing-agent-cloud@sha256:63027f22329e5cb7dafa2e2eab5e62a4cee079f2dbb61b860b0726de837259c7`.
- Build log: `tmp/agent-cloud-lima-build.log`.
- An isolated container passed the ready hook and reported `waiting-for-run`,
  empty identity/credentials and zero telemetry/video counters. Its embedded
  build ID matches the controller and source package. The temporary container
  was removed after validation.
- Smoke evidence: `tmp/agent-cloud-lima-ready.json`,
  `tmp/agent-cloud-lima-status.json`, `tmp/agent-cloud-lima-image.json`, and
  `tmp/agent-cloud-lima-smoke.log`.

## Findings and limits

The first ARM64 test run caught unsigned EC2 metadata probing in the offline
controller fixture before its explicit region was assigned. Both controller
fixtures now disable IMDS at configuration construction and retain the
signed-request assertion. The Lambda package check also corrected the loader
path to `/lib/ld-linux-aarch64.so.1`, as present in `provided.al2023`.

The successful final run includes both corrections. Earlier failed logs remain
under `tmp/agent-controller-lima-build.log` and
`tmp/agent-controller-lima-build-fixed.log`.

These artifacts do not prove AWS image activation, snapshot/restore behavior,
execution-role permissions, real KVS streams, cloud attachment or terminal VM
state after controller failure. No device run hook, AWS resource mutation,
publication, firmware flashing or commit occurred during these checks. Keep
automation disabled until the existing deployment/live acceptance gates pass.
