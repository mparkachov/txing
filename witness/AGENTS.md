# witness guide

## Scope

- This directory contains the Go Sparkplug projection Lambda.

## Rules

- Follow the repository-level workflow in `../AGENTS.md`.
- Read `../docs/sparkplug-lifecycle.md` before changing Sparkplug projection
  behavior.
- Read `../docs/aws-lambda-boundary.md` before changing Lambda packaging,
  deployment, or release behavior.
- Read `../docs/contracts/unit-device-contracts.md` before changing unit
  lifecycle, REDCON, or named-shadow projection assumptions.
- Witness is the only authority that writes the AWS-side `sparkplug` named
  shadow for rig and unit things.
- Runtime Lambdas remain Go static `linux/arm64` `provided.al2023` bootstrap
  executables published from release artifacts.
