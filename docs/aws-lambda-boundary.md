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

Existing stacks may temporarily retain legacy custom-resource service-token
functions such as `txing-enlist-lambda` and the old generated cleanup function.
Those are migration bridges only: operator commands and stack outputs point at
the `aws-*` admin functions, and the legacy functions are not release artifacts.

Runtime Lambdas are Go:

- `txing-witness-lambda`
- `txing-cloud-rig-lambda`
- `txing-cloud-mcu-lambda`

These functions stay as static `linux/arm64` `bootstrap` executables for
`provided.al2023`. They are published as release artifacts and updated by
`aws::publish` or `aws::deploy-local-lambda`.

Rust remains the implementation language for firmware, Greengrass runtime code,
and other non-Lambda Rust components. This boundary is intentionally language
based so Lambda build and release behavior stays predictable.
