# AWS Lambda Language Boundary

AWS Lambda functions in this repository are split by whether they are control
plane administration or runtime data plane.

Admin Lambdas are Python:

- `aws-publish-release`
- `aws-enlist-txing`
- `aws-clean-stack`

These functions call boto3-heavy AWS control-plane APIs for CloudFormation, S3,
IoT registry, Greengrass, SSM, and operator publishing workflows. They are
packaged with `just aws::deploy` as CloudFormation-managed stack code, not as
GitHub release runtime artifacts.
Each Lambda is owned by a dedicated nested stack under `shared/aws/templates/lambdas/`.
The template is intentionally clean-stack only: it does not contain rollback,
migration, or legacy service-token bridge modes.

Runtime Lambdas are Go:

- `txing-witness-lambda`
- `txing-cloud-rig-lambda`
- `txing-cloud-mcu-lambda`

These functions stay as static `linux/arm64` `bootstrap` executables for
`provided.al2023`. They are published as release artifacts and updated by
`aws::publish` or `aws::publish-lambda`.

Rust remains the implementation language for firmware, Greengrass runtime code,
and other non-Lambda Rust components. This boundary is intentionally language
based so Lambda build and release behavior stays predictable.
