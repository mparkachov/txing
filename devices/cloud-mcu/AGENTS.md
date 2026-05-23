# cloud MCU guide

## Scope

- This directory contains the AWS-hosted `cloud` rig and `cloud-mcu` runtime
  Lambda/device-type support.

## Rules

- Follow the repository-level workflow in `../../AGENTS.md`.
- Read `../../docs/aws-lambda-boundary.md` before changing Lambda language,
  packaging, deployment, or release boundaries.
- Read `../../docs/constraints/repository-rules.md` before changing AWS,
  CloudFormation, release, or deployment behavior.
- Runtime Lambdas remain Go static `linux/arm64` `provided.al2023` bootstrap
  executables published from release artifacts.
- Do not introduce host install paths for the `cloud` rig type; it is an
  AWS-hosted Lambda/EventBridge/SQS runtime.
