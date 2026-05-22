# AWS Lambda Language Boundary

AWS Lambda functions in this repository are split by whether they are control
plane administration or runtime data plane.

Admin Lambdas are Python. Their deployed function names are prefixed with the
environment stack name, for example `town-aws-publish-release`:

- `aws-publish-release`
- `aws-enlist-txing`
- `aws-clean-stack`

These functions call boto3-heavy AWS control-plane APIs for CloudFormation, S3,
IoT registry, SSM, and operator publishing workflows. They are
packaged by their standalone `just aws::<function>::deploy` recipes as
CloudFormation-managed stack code, not as GitHub release runtime artifacts.
Each Lambda is owned by a standalone template under `shared/aws/lambdas/`.
The template is intentionally clean-stack only: it does not contain rollback,
migration, or legacy service-token bridge modes.

Runtime Lambdas are Go. GitHub release assets and S3 object keys keep these
stable artifact ids, while deployed function names are prefixed with the
environment stack name and omit the redundant `-lambda` suffix, for example
`town-cloud-rig`:

- `txing-witness-lambda`
- `txing-cloud-rig-lambda`
- `txing-cloud-mcu-lambda`

These functions stay as static `linux/arm64` `bootstrap` executables for
`provided.al2023`. They are published as release artifacts and updated by
per-function `publish` recipes, `aws::publish`, or `aws::publish-lambda`.

Rust remains the implementation language for firmware and other non-Lambda Rust
components. Standalone rig daemons and runtime Lambdas are Go. This boundary is
intentionally language based so Lambda build and release behavior stays
predictable.
